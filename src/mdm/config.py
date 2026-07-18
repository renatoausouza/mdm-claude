import os


def get_port() -> int:
    return int(os.environ.get("MDM_PORT", "8000"))


def get_host() -> str:
    return os.environ.get("MDM_HOST", "0.0.0.0")


def get_ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def get_ollama_ready_model() -> str:
    return os.environ.get("OLLAMA_READY_MODEL", "tinyllama")


def get_data_dir() -> str:
    return os.environ.get("MDM_DATA_DIR", "data")


def get_retention_days() -> int | None:
    value = os.environ.get("MDM_RETENTION_DAYS")
    if value is None:
        return None
    try:
        days = int(value)
    except ValueError:
        raise ValueError(f"MDM_RETENTION_DAYS must be an integer, got {value!r}") from None
    if days < 0:
        raise ValueError(f"MDM_RETENTION_DAYS must not be negative, got {days}")
    return days


def get_database_url() -> str:
    return os.environ.get("MDM_DATABASE_URL", f"sqlite:///{get_data_dir()}/mdm.db")


def get_encryption_key_path() -> str:
    return os.environ.get("MDM_ENCRYPTION_KEY_PATH", f"{get_data_dir()}/encryption.key")


def get_encryption_key() -> str | None:
    return os.environ.get("MDM_ENCRYPTION_KEY")


def get_max_upload_bytes() -> int:
    return int(os.environ.get("MDM_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))  # 100 MiB default
