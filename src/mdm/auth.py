import datetime
import enum
import secrets
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mdm import config, security, storage
from mdm.db import BootstrapMarker, User, UserSession, ensure_aware_utc, get_session

router = APIRouter()


class UserRole(str, enum.Enum):
    SUBMITTER = "submitter"
    APPROVER = "approver"
    ADMIN = "admin"


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: UserRole


class UserResponse(BaseModel):
    id: str
    username: str
    role: str


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(payload: CreateUserRequest, authorization: str | None = Header(default=None)) -> UserResponse:
    with get_session() as session:
        is_first_user = session.query(User).count() == 0

        if is_first_user:
            # BootstrapMarker's primary key makes "am I really first" an
            # atomic, DB-enforced claim instead of a racy count()==0 read:
            # if two requests race here, only one can successfully insert
            # this row: the loser falls through to the normal admin-auth
            # path below (and is correctly rejected, since it has none).
            session.add(BootstrapMarker(id="bootstrap"))
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                is_first_user = False

        if not is_first_user:
            # Not a Depends() here: whether auth is even required depends on
            # runtime DB state (is this truly the first user?) discovered
            # inside this same function — a Depends() dependency runs
            # unconditionally before the route body, so it can't express
            # "only required if this turns out not to be the bootstrap case".
            current_user = get_current_user(authorization)
            if current_user.role != UserRole.ADMIN.value:
                raise HTTPException(status_code=403, detail="Only admins can create users")

        if session.query(User).filter_by(username=payload.username).first() is not None:
            raise HTTPException(status_code=409, detail="Username already exists")

        role = UserRole.ADMIN.value if is_first_user else payload.role.value

        user = User(
            id=str(uuid.uuid4()),
            username=payload.username,
            password_hash=security.hash_password(payload.password),
            role=role,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="Username already exists") from None

        return UserResponse(id=user.id, username=user.username, role=user.role)


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None


class LoginResponse(BaseModel):
    token: str
    role: str
    mfa_enrollment_required: bool = False


def _register_failed_attempt(session: Session, user: User) -> None:
    # Atomic SQL increment (not a Python read-modify-write on the ORM
    # object) so concurrent failed logins for the same user can't lose an
    # update and undercount toward the lockout threshold.
    session.execute(
        update(User).where(User.id == user.id).values(failed_login_attempts=User.failed_login_attempts + 1)
    )
    session.commit()
    session.refresh(user)

    if user.failed_login_attempts >= config.get_max_failed_login_attempts():
        user.locked_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=config.get_lockout_duration_minutes()
        )
        session.commit()


def _issue_session(session: Session, user: User, scope: str, now: datetime.datetime) -> str:
    token = secrets.token_urlsafe(32)
    duration = (
        datetime.timedelta(minutes=config.get_mfa_enrollment_session_duration_minutes())
        if scope == "mfa_enrollment"
        else datetime.timedelta(hours=config.get_session_duration_hours())
    )
    user_session = UserSession(
        token=token,
        user_id=user.id,
        scope=scope,
        created_at=now,
        expires_at=now + duration,
    )
    session.add(user_session)
    session.commit()
    return token


def _verify_and_consume_totp(session: Session, user: User, code: str) -> bool:
    """Checks the code AND that it wasn't the last code already accepted
    for this user — pyotp's verify() alone doesn't prevent replaying an
    observed/captured code again within its ~90s validity window."""
    secret = storage.decrypt_text(user.totp_secret) if user.totp_secret else None
    if secret is None or not security.verify_totp(secret, code):
        return False
    if code == user.last_used_totp_code:
        return False
    user.last_used_totp_code = code
    session.commit()
    return True


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    with get_session() as session:
        user = session.query(User).filter_by(username=payload.username).first()
        if user is None:
            # Run a real (failing) hash verify so this path takes about as
            # long as the "user exists, wrong password" path below — the
            # difference is a timing side-channel an attacker can use to
            # enumerate valid usernames.
            security.verify_password(payload.password, security.DUMMY_PASSWORD_HASH)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        now = datetime.datetime.now(datetime.timezone.utc)
        # Locked-out accounts get the same generic 401 as a bad password —
        # a distinct status (e.g. 423) would directly reveal, with no
        # timing analysis needed, that this username exists and is locked.
        if user.locked_until is not None and ensure_aware_utc(user.locked_until) > now:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not security.verify_password(payload.password, user.password_hash):
            _register_failed_attempt(session, user)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        is_approver = user.role == UserRole.APPROVER.value

        if is_approver and not user.totp_enrolled:
            user.failed_login_attempts = 0
            user.locked_until = None
            session.commit()
            token = _issue_session(session, user, scope="mfa_enrollment", now=now)
            return LoginResponse(token=token, role=user.role, mfa_enrollment_required=True)

        if is_approver and user.totp_enrolled:
            if payload.totp_code is None or not _verify_and_consume_totp(session, user, payload.totp_code):
                _register_failed_attempt(session, user)
                raise HTTPException(status_code=401, detail="Invalid or missing TOTP code")

        user.failed_login_attempts = 0
        user.locked_until = None
        session.commit()

        token = _issue_session(session, user, scope="full", now=now)
        return LoginResponse(token=token, role=user.role)


def _authenticate(authorization: str | None, required_scope: str) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")

    with get_session() as session:
        user_session = session.query(UserSession).filter_by(token=token).first()
        if user_session is None:
            raise HTTPException(status_code=401, detail="Invalid session token")

        now = datetime.datetime.now(datetime.timezone.utc)
        if ensure_aware_utc(user_session.expires_at) < now:
            raise HTTPException(status_code=401, detail="Session expired")

        # Exact match only — a "full" session must NOT satisfy an
        # "mfa_enrollment" requirement. That scope exists specifically so
        # an unenrolled approver can reach only the enrollment endpoints;
        # letting a "full" session through here would let a stolen full
        # session silently re-provision MFA on an already-enrolled account
        # with no password or TOTP re-check.
        if user_session.scope != required_scope:
            raise HTTPException(status_code=403, detail="Session scope does not permit this action")

        user = session.query(User).filter_by(id=user_session.user_id).first()
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid session token")
        return user


def get_current_user(authorization: str | None = Header(default=None)) -> User:
    """FastAPI dependency: `Depends(get_current_user)` — requires a normal,
    fully-authenticated ("full" scope) session."""
    return _authenticate(authorization, required_scope="full")


def get_enrollment_scoped_user(authorization: str | None = Header(default=None)) -> User:
    """FastAPI dependency: `Depends(get_enrollment_scoped_user)` — requires
    the narrow "mfa_enrollment" scope issued to an unenrolled approver.
    Deliberately does NOT also accept a "full" session (see _authenticate's
    exact-match comment) — that would let a stolen full session
    re-provision MFA on an already-enrolled account with no re-verification."""
    return _authenticate(authorization, required_scope="mfa_enrollment")


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None), current_user: User = Depends(get_current_user)) -> dict[str, str]:
    assert authorization is not None  # get_current_user already validated it
    token = authorization.removeprefix("Bearer ")
    with get_session() as session:
        session.query(UserSession).filter_by(token=token).delete()
        session.commit()
    return {"status": "logged out"}


class MfaEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str


@router.post("/auth/mfa/enroll", response_model=MfaEnrollResponse)
def enroll_mfa(current_user: User = Depends(get_enrollment_scoped_user)) -> MfaEnrollResponse:
    with get_session() as session:
        user = session.query(User).filter_by(id=current_user.id).first()
        assert user is not None
        secret = security.generate_totp_secret()
        user.totp_secret = storage.encrypt_text(secret)
        user.totp_enrolled = False
        session.commit()
        return MfaEnrollResponse(
            secret=secret,
            provisioning_uri=security.totp_provisioning_uri(secret, user.username),
        )


class VerifyMfaRequest(BaseModel):
    totp_code: str


@router.post("/auth/mfa/verify")
def verify_mfa(
    payload: VerifyMfaRequest, current_user: User = Depends(get_enrollment_scoped_user)
) -> dict[str, str]:
    with get_session() as session:
        user = session.query(User).filter_by(id=current_user.id).first()
        assert user is not None
        if user.totp_secret is None:
            raise HTTPException(status_code=400, detail="No MFA enrollment in progress")
        if not _verify_and_consume_totp(session, user, payload.totp_code):
            raise HTTPException(status_code=401, detail="Invalid TOTP code")
        user.totp_enrolled = True
        session.commit()
        return {"status": "enrolled"}
