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


def get_oci_config_file_path() -> str | None:
    # None lets the OCI SDK fall back to its own default (~/.oci/config) —
    # only set MDM_OCI_CONFIG_FILE to point at a non-standard location.
    return os.environ.get("MDM_OCI_CONFIG_FILE")


def get_oci_config_profile() -> str:
    return os.environ.get("MDM_OCI_CONFIG_PROFILE", "DEFAULT")


def get_oci_genai_compartment_id() -> str:
    value = os.environ.get("MDM_OCI_GENAI_COMPARTMENT_ID")
    if not value:
        raise RuntimeError("MDM_OCI_GENAI_COMPARTMENT_ID must be set to call OCI Generative AI")
    return value


def get_oci_genai_model_id() -> str:
    # meta.llama-3.3-70b-instruct: current (as of writing) on-demand Meta
    # Llama model in OCI Generative AI — closest behavioral match to the
    # llama3 model this replaces. Override if your tenancy/region offers a
    # different on-demand model, or the catalog rotates this one out.
    return os.environ.get("MDM_OCI_GENAI_MODEL_ID", "meta.llama-3.3-70b-instruct")


def get_oci_genai_service_endpoint() -> str:
    explicit = os.environ.get("MDM_OCI_GENAI_SERVICE_ENDPOINT")
    if explicit:
        return explicit
    region = os.environ.get("MDM_OCI_GENAI_REGION")
    if not region:
        raise RuntimeError(
            "Set MDM_OCI_GENAI_SERVICE_ENDPOINT, or MDM_OCI_GENAI_REGION so the endpoint can be derived from it"
        )
    return f"https://inference.generativeai.{region}.oci.oraclecloud.com"


def get_oci_genai_extraction_timeout_seconds() -> float:
    # deploy/nginx-mdm.conf grants POST /documents up to 300s. That budget
    # was sized for CPU-only local inference (50-90s observed); a managed
    # cloud model call is expected to be far faster, but the ceiling is
    # left high enough to still cover network/service variance without
    # nginx giving up first.
    return float(os.environ.get("MDM_OCI_GENAI_EXTRACTION_TIMEOUT_SECONDS", "120"))


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
