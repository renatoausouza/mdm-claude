import socket
import sys

import uvicorn
from fastapi import Depends, FastAPI, Request, Response

from mdm import config
from mdm.audit import router as audit_router
from mdm.auth import router as auth_router
from mdm.dashboard import router as dashboard_router
from mdm.documents import router as documents_router
from mdm.duplicates import router as duplicates_router
from mdm.i18n import bind_language, reset_language
from mdm.ollama_client import OllamaClient
from mdm.review import router as review_router

app = FastAPI(title="mdm")
app.include_router(documents_router)
app.include_router(auth_router)
app.include_router(review_router)
app.include_router(duplicates_router)
app.include_router(audit_router)
app.include_router(dashboard_router)


@app.middleware("http")
async def language_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Binds the request's resolved language (X-MDM-Language header) to a
    ContextVar for the duration of this request — see mdm.i18n.t(). This
    reaches every t() call in the request's call graph, including ones
    several calls deep in helpers that never see the request/header
    directly (e.g. auth.py's _authenticate, reached via the
    get_current_user dependency), without threading a language parameter
    through every function signature in between.

    Sync route handlers in this app run in Starlette's threadpool
    (run_in_threadpool -> anyio.to_thread.run_sync), which copies the
    current contextvars Context into the worker thread by default — so the
    binding set here is visible there too, not just in async code.
    """
    token = bind_language(request.headers.get("x-mdm-language"))
    try:
        return await call_next(request)
    finally:
        reset_language(token)


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
