import socket
import sys

import uvicorn
from fastapi import Depends, FastAPI, Response

from mdm import config
from mdm.ollama_client import OllamaClient

app = FastAPI(title="mdm")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def get_ollama_client() -> OllamaClient:
    return OllamaClient()


@app.get("/ready")
def ready(response: Response, client: OllamaClient = Depends(get_ollama_client)) -> dict[str, str]:
    if client.check():
        return {"status": "ready"}
    response.status_code = 503
    return {"status": "not ready"}


def resolve_bind_address(host: str | None, port: int | None) -> tuple[str, int]:
    """Resolve explicit overrides against config defaults.

    Uses an explicit None check (not a falsy check) so that host="" or
    port=0 — both legitimate values, not "unset" — are honored rather than
    silently replaced by the config default.
    """
    resolved_host = host if host is not None else config.get_host()
    resolved_port = port if port is not None else config.get_port()
    return resolved_host, resolved_port


def run(host: str | None = None, port: int | None = None) -> None:
    """Bind to a single fixed port. Fails fast (SystemExit) if unavailable —
    never falls back to a different port.

    The port check below is an explicit, in-repo guarantee: it does not rely
    on uvicorn's internal bind-failure behavior (which could change between
    versions), and it also protects against a future change that wraps this
    call in a broad try/except and retries with a different port.
    """
    resolved_host, resolved_port = resolve_bind_address(host, port)

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((resolved_host, resolved_port))
    except OSError as exc:
        print(f"Cannot start: port {resolved_port} on {resolved_host} is unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        probe.close()

    uvicorn.run(app, host=resolved_host, port=resolved_port)


if __name__ == "__main__":
    run()
