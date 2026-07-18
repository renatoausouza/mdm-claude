import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet

from mdm import config

logger = logging.getLogger(__name__)


@lru_cache
def _load_or_create_key(key_path: str, env_key: str | None) -> bytes:
    if env_key is not None:
        return env_key.encode()

    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read()

    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
    candidate_key = Fernet.generate_key()
    try:
        # O_EXCL is atomic: if two callers race here, only one wins the
        # create and the other gets FileExistsError below, avoiding the
        # "both generate a different key and overwrite each other" race.
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        with open(key_path, "rb") as f:
            return f.read()

    with os.fdopen(fd, "wb") as f:
        f.write(candidate_key)
    logger.warning(
        "Generated a new document-encryption key at %s. Back this up — "
        "losing it makes all stored documents unrecoverable.",
        key_path,
    )
    return candidate_key


def _get_or_create_key() -> bytes:
    return _load_or_create_key(config.get_encryption_key_path(), config.get_encryption_key())


def encrypt_text(value: str) -> str:
    """Encrypt an arbitrary string at rest using the same key/mechanism as
    document storage (e.g. for other secrets, like a TOTP seed, that need
    the same confidentiality guarantee as stored documents)."""
    return Fernet(_get_or_create_key()).encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    return Fernet(_get_or_create_key()).decrypt(value.encode()).decode()


def _documents_dir() -> str:
    path = os.path.join(config.get_data_dir(), "documents")
    os.makedirs(path, exist_ok=True)
    return path


def _document_path(document_id: str) -> str:
    return os.path.join(_documents_dir(), document_id)


def save_document(document_id: str, content: bytes) -> str:
    # TODO: single key, no key-id/version stored with the ciphertext. Fine
    # for now, but rotating this key later means every existing document
    # becomes unreadable unless re-encrypted before the old key is retired —
    # revisit if/when key rotation becomes a real requirement.
    fernet = Fernet(_get_or_create_key())
    encrypted = fernet.encrypt(content)
    path = _document_path(document_id)
    with open(path, "wb") as f:
        f.write(encrypted)
    return path


def read_document(document_id: str) -> bytes:
    fernet = Fernet(_get_or_create_key())
    with open(_document_path(document_id), "rb") as f:
        encrypted = f.read()
    return fernet.decrypt(encrypted)


def document_exists(document_id: str) -> bool:
    return os.path.exists(_document_path(document_id))


def delete_document(document_id: str) -> None:
    # Idempotent: called by the retention-purge job, which should be safe to
    # re-run against a document it already purged.
    try:
        os.remove(_document_path(document_id))
    except FileNotFoundError:
        pass
