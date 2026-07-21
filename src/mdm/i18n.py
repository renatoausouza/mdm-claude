import contextvars
from contextlib import contextmanager
from typing import Iterator

SUPPORTED_LANGUAGES = ("en", "pt")

# The server-side default when no X-MDM-Language header is present at all.
# Deliberately English, not the frontend's own PT-first default (see
# tests/test_i18n.py) — the frontend always sends this header explicitly
# once wired up, so this only matters for callers that don't know about it.
DEFAULT_LANGUAGE = "en"

_current_language: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mdm_current_language", default=DEFAULT_LANGUAGE
)


def resolve_language(header_value: str | None) -> str:
    if header_value is None:
        return DEFAULT_LANGUAGE
    normalized = header_value.strip().lower()
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    return DEFAULT_LANGUAGE


def bind_language(header_value: str | None) -> contextvars.Token[str]:
    """Resolve the X-MDM-Language header and bind it for the current
    context (request). Called once, by the ASGI middleware in main.py —
    every t() call anywhere in that request's call graph, however deeply
    nested, reads it back without needing the value threaded through
    function signatures."""
    return _current_language.set(resolve_language(header_value))


def reset_language(token: contextvars.Token[str]) -> None:
    _current_language.reset(token)


@contextmanager
def language_context(lang: str) -> Iterator[None]:
    """Test/script helper — sets the current-language context for the
    duration of a `with` block."""
    token = _current_language.set(lang)
    try:
        yield
    finally:
        _current_language.reset(token)


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    """Translate `key` into the current (or explicitly given) language.
    Falls back to English, then to the raw key itself, if a translation is
    missing — a missing entry should degrade to *something readable*, never
    crash a request."""
    if lang is None:
        lang = _current_language.get()
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    template = entry.get(lang) or entry.get("en") or key
    if kwargs:
        return template.format(**kwargs)
    return template


# One entry per distinct backend-facing message (HTTPException details).
# Dynamic messages use str.format()-style placeholders, filled in by the
# caller via t(key, **kwargs).
MESSAGES: dict[str, dict[str, str]] = {
    "missing_auth_header": {
        "en": "Missing or malformed Authorization header",
        "pt": "Cabeçalho de autorização ausente ou inválido",
    },
    "username_exists": {
        "en": "Username already exists",
        "pt": "Nome de usuário já existe",
    },
    "invalid_credentials": {
        "en": "Invalid credentials",
        "pt": "Credenciais inválidas",
    },
    "invalid_session_token": {
        "en": "Invalid session token",
        "pt": "Token de sessão inválido",
    },
    "session_expired": {
        "en": "Session expired",
        "pt": "Sessão expirada",
    },
    "session_scope_denied": {
        "en": "Session scope does not permit this action",
        "pt": "O escopo da sessão não permite esta ação",
    },
    "no_mfa_enrollment": {
        "en": "No MFA enrollment in progress",
        "pt": "Nenhum cadastro de autenticação de dois fatores em andamento",
    },
    "invalid_totp_code": {
        "en": "Invalid TOTP code",
        "pt": "Código TOTP inválido",
    },
    "admin_only_create_user": {
        "en": "Only admins can create users",
        "pt": "Somente administradores podem criar usuários",
    },
    "invalid_or_missing_totp": {
        "en": "Invalid or missing TOTP code",
        "pt": "Código TOTP inválido ou ausente",
    },
    "unsupported_domain": {
        "en": "Unsupported domain: {domain} (must be one of {choices})",
        "pt": "Domínio não suportado: {domain} (deve ser um de {choices})",
    },
    "unsupported_file_type": {
        "en": "Unsupported file type: {extension}",
        "pt": "Tipo de arquivo não suportado: {extension}",
    },
    "upload_too_large": {
        "en": "File exceeds the {max_bytes}-byte upload limit",
        "pt": "O arquivo excede o limite de envio de {max_bytes} bytes",
    },
    "unknown_domain": {
        "en": "Unknown domain: {domain} (must be one of {choices})",
        "pt": "Domínio desconhecido: {domain} (deve ser um de {choices})",
    },
    "job_not_found": {
        "en": "Job not found",
        "pt": "Registro não encontrado",
    },
    "document_file_missing": {
        "en": "Document record exists but its stored file is missing",
        "pt": "O registro do documento existe, mas o arquivo armazenado está ausente",
    },
    "duplicate_case_not_found": {
        "en": "Duplicate review case not found",
        "pt": "Caso de revisão de duplicidade não encontrado",
    },
    "partial_requires_accepted_fields": {
        "en": "partial resolution requires accepted_fields",
        "pt": "a resolução parcial requer accepted_fields",
    },
    "duplicate_case_already_resolved": {
        "en": "Duplicate review case already resolved (status={status})",
        "pt": "Caso de revisão de duplicidade já resolvido (status={status})",
    },
    "segregation_cannot_resolve_own": {
        "en": "Segregation of duties: you cannot resolve a duplicate for your own submission",
        "pt": "Segregação de funções: você não pode resolver uma duplicidade da sua própria submissão",
    },
    "matched_record_superseded": {
        "en": "The matched record has been superseded by another update since this case was created — "
        "re-check for a duplicate against the current version before resolving this case",
        "pt": "O registro correspondente foi substituído por outra atualização desde que este caso foi "
        "criado — verifique novamente se há duplicidade em relação à versão atual antes de resolver este caso",
    },
    "job_already_decided": {
        "en": "Job was already decided by another request",
        "pt": "O registro já foi decidido por outra solicitação",
    },
    "master_record_not_found": {
        "en": "No current master record found with that id",
        "pt": "Nenhum registro mestre atual encontrado com esse id",
    },
    "cannot_link_domain_mismatch": {
        "en": "Cannot link a {domain} candidate to a {other_domain} record",
        "pt": "Não é possível vincular um candidato de {domain} a um registro de {other_domain}",
    },
    "unknown_fields_accepted": {
        "en": "Unknown field(s) in accepted_fields: {fields}",
        "pt": "Campo(s) desconhecido(s) em accepted_fields: {fields}",
    },
    "matched_record_updated_concurrently": {
        "en": "The matched record was updated by another request just now — "
        "re-check for a duplicate against the current version before resolving this case",
        "pt": "O registro correspondente foi atualizado por outra solicitação agora mesmo — "
        "verifique novamente se há duplicidade em relação à versão atual antes de resolver este caso",
    },
    "job_just_linked_duplicate": {
        "en": "This job was just linked to a duplicate case by another request",
        "pt": "Este registro acabou de ser vinculado a um caso de duplicidade por outra solicitação",
    },
    "approver_only_decisions": {
        "en": "Only approver accounts may make review decisions",
        "pt": "Somente contas de aprovador podem tomar decisões de revisão",
    },
    "job_not_awaiting_decision": {
        "en": "Job is not awaiting a review decision (status={status})",
        "pt": "O registro não está aguardando uma decisão de revisão (status={status})",
    },
    "job_has_pending_duplicate": {
        "en": "Job has a pending duplicate review case ({case_id}) — "
        "resolve it via POST /duplicates/{case_id}/resolve instead",
        "pt": "O registro tem um caso de revisão de duplicidade pendente ({case_id}) — "
        "resolva-o via POST /duplicates/{case_id}/resolve",
    },
    "segregation_cannot_approve_own": {
        "en": "Segregation of duties: you cannot approve your own submission for this domain",
        "pt": "Segregação de funções: você não pode aprovar sua própria submissão para este domínio",
    },
    "matching_record_found": {
        "en": "A matching {domain} record already exists — duplicate review case {case_id} created; "
        "resolve it via POST /duplicates/{case_id}/resolve instead",
        "pt": "Já existe um registro de {domain} correspondente — caso de revisão de duplicidade "
        "{case_id} criado; resolva-o via POST /duplicates/{case_id}/resolve",
    },
    "unknown_fields_overrides": {
        "en": "Unknown field(s) in field_overrides: {fields}",
        "pt": "Campo(s) desconhecido(s) em field_overrides: {fields}",
    },
    "record_registered_concurrently": {
        "en": "A matching record was just registered by another request — "
        "retry to pick up the resulting duplicate review case",
        "pt": "Um registro correspondente acabou de ser cadastrado por outra solicitação — "
        "tente novamente para localizar o caso de duplicidade resultante",
    },
    "admin_only_audit_log": {
        "en": "Only admin accounts may view the audit log",
        "pt": "Somente contas de administrador podem visualizar o log de auditoria",
    },
    "approver_or_admin_only": {
        "en": "Only approver or admin accounts may view master data",
        "pt": "Somente contas de aprovador ou administrador podem visualizar os dados mestres",
    },
    "key_field_not_editable": {
        "en": "The key field ({field}) cannot be edited — it is the record's stable identity",
        "pt": "O campo-chave ({field}) não pode ser editado — é a identidade estável do registro",
    },
    "direct_edit_not_allowed_for_domain": {
        "en": "This domain requires an edit request reviewed by a second approver, not a direct edit",
        "pt": "Este domínio exige uma solicitação de edição revisada por um segundo aprovador, não uma edição direta",
    },
    "record_changed_concurrently": {
        "en": "This record was changed by another request — reload it and try again",
        "pt": "Este registro foi alterado por outra solicitação — recarregue e tente novamente",
    },
}
