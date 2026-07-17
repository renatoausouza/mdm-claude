import os


def get_port() -> int:
    return int(os.environ.get("MDM_PORT", "8000"))


def get_host() -> str:
    return os.environ.get("MDM_HOST", "0.0.0.0")


def get_ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def get_ollama_ready_model() -> str:
    return os.environ.get("OLLAMA_READY_MODEL", "tinyllama")
