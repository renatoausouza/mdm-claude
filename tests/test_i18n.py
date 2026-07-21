from fastapi.testclient import TestClient

from mdm.i18n import language_context, resolve_language, t
from mdm.main import app

# The server-side fallback (no header at all) is English, not the
# frontend's own PT-first default — the frontend always sends this header
# explicitly once it's wired up, so this fallback only matters for callers
# that don't know about it (bare API calls, this test suite). Defaulting
# the *server* to Portuguese would silently change every existing test's
# expected English error strings.


def test_resolve_language_accepts_pt() -> None:
    assert resolve_language("pt") == "pt"


def test_resolve_language_accepts_en() -> None:
    assert resolve_language("en") == "en"


def test_resolve_language_defaults_to_english_when_missing() -> None:
    assert resolve_language(None) == "en"


def test_resolve_language_defaults_to_english_when_unrecognized() -> None:
    assert resolve_language("fr") == "en"


def test_resolve_language_is_case_insensitive() -> None:
    assert resolve_language("PT") == "pt"


def test_t_looks_up_explicit_language_english() -> None:
    assert t("job_not_found", lang="en") == "Job not found"


def test_t_looks_up_explicit_language_portuguese() -> None:
    assert t("job_not_found", lang="pt") == "Registro não encontrado"


def test_t_formats_placeholders() -> None:
    assert t("unsupported_file_type", lang="en", extension=".exe") == "Unsupported file type: .exe"


def test_t_falls_back_to_english_for_unknown_key() -> None:
    assert t("this_key_does_not_exist", lang="pt") == "this_key_does_not_exist"


def test_t_reads_language_from_context_when_not_given_explicitly() -> None:
    with language_context("pt"):
        assert t("job_not_found") == "Registro não encontrado"
    with language_context("en"):
        assert t("job_not_found") == "Job not found"


# --- integration: the middleware must reach a request-scoped language all
# the way down to deeply-nested helpers (auth.py's _authenticate, used by
# the get_current_user dependency on nearly every protected route) without
# any function signature being changed to accept a language parameter. ---


def test_login_error_is_translated_pre_auth() -> None:
    client = TestClient(app)

    default_response = client.post("/auth/login", json={"username": "nobody", "password": "wrong"})
    assert default_response.json()["detail"] == "Invalid credentials"

    pt_response = client.post(
        "/auth/login",
        json={"username": "nobody", "password": "wrong"},
        headers={"X-MDM-Language": "pt"},
    )
    assert pt_response.json()["detail"] == "Credenciais inválidas"


def test_deeply_nested_auth_helper_honors_language_header() -> None:
    client = TestClient(app)

    # No Authorization header at all — hits _authenticate's very first
    # check, several calls below the route handler, via get_current_user's
    # Depends() chain.
    default_response = client.get("/jobs")
    assert default_response.json()["detail"] == "Missing or malformed Authorization header"

    pt_response = client.get("/jobs", headers={"X-MDM-Language": "pt"})
    assert pt_response.json()["detail"] == "Cabeçalho de autorização ausente ou inválido"
