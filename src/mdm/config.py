import os


def _positive_int(env_var: str, default: str) -> int:
    value = os.environ.get(env_var, default)
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(f"{env_var} must be an integer, got {value!r}") from None
    if parsed < 0:
        raise ValueError(f"{env_var} must not be negative, got {parsed}")
    return parsed


def get_port() -> int:
    return int(os.environ.get("MDM_PORT", "8000"))


def get_host() -> str:
    return os.environ.get("MDM_HOST", "0.0.0.0")


def get_ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def get_ollama_ready_model() -> str:
    return os.environ.get("OLLAMA_READY_MODEL", "tinyllama")


def get_ollama_extraction_model() -> str:
    # Distinct from the readiness-check model: extraction needs a model
    # actually capable of structured JSON output, not just a cheap liveness
    # ping — tinyllama is too weak for this.
    return os.environ.get("OLLAMA_EXTRACTION_MODEL", "llama3")


def get_data_dir() -> str:
    return os.environ.get("MDM_DATA_DIR", "data")


def get_retention_days() -> int | None:
    if os.environ.get("MDM_RETENTION_DAYS") is None:
        return None
    return _positive_int("MDM_RETENTION_DAYS", "0")


def get_database_url() -> str:
    return os.environ.get("MDM_DATABASE_URL", f"sqlite:///{get_data_dir()}/mdm.db")


def get_encryption_key_path() -> str:
    return os.environ.get("MDM_ENCRYPTION_KEY_PATH", f"{get_data_dir()}/encryption.key")


def get_encryption_key() -> str | None:
    return os.environ.get("MDM_ENCRYPTION_KEY")


def get_max_upload_bytes() -> int:
    return _positive_int("MDM_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024))  # 100 MiB default


def get_max_failed_login_attempts() -> int:
    return _positive_int("MDM_MAX_FAILED_LOGIN_ATTEMPTS", "5")


def get_lockout_duration_minutes() -> int:
    return _positive_int("MDM_LOCKOUT_DURATION_MINUTES", "15")


def get_session_duration_hours() -> int:
    return _positive_int("MDM_SESSION_DURATION_HOURS", "24")


def get_mfa_enrollment_session_duration_minutes() -> int:
    return _positive_int("MDM_MFA_ENROLLMENT_SESSION_DURATION_MINUTES", "10")


def get_confidence_threshold() -> float:
    # Below this, a field forces human review regardless of the overall
    # reliability tier (D16). Default sits strictly between ticket #4's two
    # LLM confidence tiers (0.3 "not found in source", 0.9 "found") so it
    # correctly routes only the unverified tier to review.
    value = os.environ.get("MDM_CONFIDENCE_THRESHOLD", "0.7")
    try:
        threshold = float(value)
    except ValueError:
        raise ValueError(f"MDM_CONFIDENCE_THRESHOLD must be a number, got {value!r}") from None
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"MDM_CONFIDENCE_THRESHOLD must be between 0 and 1, got {threshold}")
    return threshold
