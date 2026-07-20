# MDM — Master Data Registration Automation

Extracts supplier, client, and product master data candidates from incoming business documents (PDF, MSG, JSON, XML, TXT/LOG, images) using a hybrid regex + local-LLM pipeline, then routes every candidate through mandatory human review before anything is registered. Runs fully offline — no PII ever leaves the host.

See [docs/solution-brief.md](docs/solution-brief.md) for the full design (problem statement, data model, scoring formulas, LGPD/security controls, roadmap).

## Design principles

- **No autonomous registration.** The LLM (local Ollama) produces advisory candidate text/JSON only — zero tool-calling, zero state changes. A human must explicitly approve every new or updated master record.
- **Deterministic duplicate detection only.** Exact-match CPF/CNPJ (supplier/client) or SKU (product). No fuzzy matching, no auto-merge — matches are linked and flagged for human review.
- **Evidence trail.** Every extracted field carries `{value, confidence, provenance}`; approvals, rejections, and duplicate resolutions are recorded in an append-only audit log.
- **Segregation of duties.** Supplier creation and sensitive-field updates require submitter ≠ approver; approver accounts require TOTP MFA.
- **Offline-first.** Extraction runs against a local Ollama model; the service is designed to run without outbound calls carrying PII.

## Repository layout

```
src/mdm/       FastAPI backend (auth, documents, extraction, scoring, duplicates, review, audit)
frontend/      React + TypeScript SPA (upload, review queues, audit log)
tests/         pytest suite
deploy/        systemd units, nginx config, install/uninstall scripts (OCI VM target)
docs/          solution brief, ADRs, agent-facing docs
```

## Prerequisites

- Python 3.10+
- Node.js + npm (for the frontend)
- [Ollama](https://ollama.ai) running locally, with the extraction and readiness models pulled (defaults: `llama3` and `tinyllama` — see [src/mdm/config.py](src/mdm/config.py))

## Backend setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# run the API server (binds to a fixed port, fails fast if unavailable)
python -m mdm.main

# run tests
pytest

# type-check
mypy
```

Configuration is environment-variable driven — see [src/mdm/config.py](src/mdm/config.py) for the full list (`MDM_HOST`, `MDM_PORT`, `MDM_DATABASE_URL`, `MDM_DATA_DIR`, `MDM_ENCRYPTION_KEY_PATH`, `OLLAMA_BASE_URL`, `MDM_CONFIDENCE_THRESHOLD`, etc.). Sensible defaults are used when unset.

## Frontend setup

```bash
cd frontend
npm install
npm run dev      # local dev server
npm run build     # production build (served by nginx in deployment)
npm run lint
```

## Deployment

`deploy/install.sh` provisions a single-VM deployment (target: an OCI VM): a dedicated non-root service user, a hardened systemd unit for the API, a systemd timer for the retention/purge job, and an nginx reverse proxy terminating TLS in front of a fixed application port. See [deploy/](deploy/) and `docs/solution-brief.md` §17 for details. Run with `sudo ./deploy/install.sh` from the repo root; reverse with `deploy/uninstall.sh`.

## Status

Actively under development — see open tickets in the repository's GitHub issues and [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md) for how work is tracked. The solution brief documents several ASSUMED DEFAULT decisions (retention duration, DPO designation, legal-basis sign-off) that are still pending business/legal input before production go-live.
