# MDM — Master Data Registration Automation

Extracts supplier, client, and product master data candidates from incoming business documents (PDF, MSG, JSON, XML, TXT/LOG, images) using a hybrid regex + LLM pipeline, then routes every candidate through mandatory human review before anything is registered. LLM calls run against OCI Generative AI (within your own OCI tenancy/compartment, over TLS) — document text and extracted fields leave the host for that call, but never any third party outside your tenancy.

See [docs/solution-brief.md](docs/solution-brief.md) for the full design (problem statement, data model, scoring formulas, LGPD/security controls, roadmap).

## Design principles

- **No autonomous registration.** The LLM (OCI Generative AI) produces advisory candidate text/JSON only — zero tool-calling, zero state changes. A human must explicitly approve every new or updated master record.
- **Deterministic duplicate detection only.** Exact-match CPF/CNPJ (supplier/client) or SKU (product). No fuzzy matching, no auto-merge — matches are linked and flagged for human review.
- **Evidence trail.** Every extracted field carries `{value, confidence, provenance}`; approvals, rejections, and duplicate resolutions are recorded in an append-only audit log.
- **Segregation of duties.** Supplier creation and sensitive-field updates require submitter ≠ approver; approver accounts require TOTP MFA.
- **PII leaves the host only for the model call.** Extraction and chat-query prompts go to OCI Generative AI in your own tenancy/compartment over TLS — not a local model, and not a third party outside OCI. This replaced an earlier fully-offline local-Ollama design; see [docs/solution-brief.md](docs/solution-brief.md) NFR-07 for the current network-egress posture.

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
- An OCI tenancy with access to Generative AI — see [OCI Generative AI setup](#oci-generative-ai-setup) below.

## OCI Generative AI setup

Extraction and the chat-query feature call OCI Generative AI (Meta Llama, on-demand) instead of a local model. You need an API signing key for a user with access to `generative-ai-family` in your target compartment, and OCI Generative AI must be available in the region you choose (check the [models-by-region page](https://docs.oracle.com/en-us/iaas/Content/generative-ai/model-endpoint-regions.htm) — it's not offered in every region).

1. **Generate an RSA key pair** (the private key never has to leave the host running the app):
   ```bash
   mkdir -p data/oci
   openssl genrsa -out data/oci/oci_api_key.pem 2048
   openssl rsa -pubout -in data/oci/oci_api_key.pem -out data/oci/oci_api_key_public.pem
   chmod 600 data/oci/oci_api_key.pem
   ```
2. **Add the public key in the OCI Console**: profile icon (top right) → **My profile** → **API keys** → **Add API key** → **Paste public key** → paste the contents of `data/oci/oci_api_key_public.pem`. The console shows a fingerprint after you add it.
3. **Collect four values**: your **Tenancy OCID** (profile icon → **Tenancy**), your **User OCID** (the My profile page from step 2), the **region** you're using, and the **compartment OCID** you want Generative AI usage scoped to (the tenancy OCID works if you don't have a dedicated compartment).
4. **Write `data/oci/config`**:
   ```ini
   [DEFAULT]
   user=<your user OCID>
   fingerprint=<fingerprint from step 2>
   tenancy=<your tenancy OCID>
   region=<your region, e.g. sa-saopaulo-1>
   key_file=<absolute path to data/oci/oci_api_key.pem>
   ```
5. **Confirm an IAM policy grants access**, e.g.:
   ```
   Allow group <your-group> to use generative-ai-family in compartment <your-compartment>
   ```
6. **Set the app's compartment/region env vars** — see [src/mdm/config.py](src/mdm/config.py) for the full list (`MDM_OCI_GENAI_COMPARTMENT_ID`, `MDM_OCI_GENAI_REGION`, `MDM_OCI_CONFIG_FILE`, `MDM_OCI_CONFIG_PROFILE`, `MDM_OCI_GENAI_MODEL_ID`). In a systemd deployment, pass `OCI_GENAI_COMPARTMENT_ID`/`OCI_GENAI_REGION` to `deploy/install.sh` and it templates them into the unit file (see Deployment below).
7. **Verify**: start the app and hit `GET /ready` — it calls OCI Generative AI's `list_models` (a control-plane read, not a billed completion) to confirm the config, key, and IAM policy all actually work together.

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

Configuration is environment-variable driven — see [src/mdm/config.py](src/mdm/config.py) for the full list (`MDM_HOST`, `MDM_PORT`, `MDM_DATABASE_URL`, `MDM_DATA_DIR`, `MDM_ENCRYPTION_KEY_PATH`, `MDM_OCI_GENAI_COMPARTMENT_ID`, `MDM_OCI_GENAI_REGION`, `MDM_CONFIDENCE_THRESHOLD`, etc.). Sensible defaults are used when unset, except the OCI Generative AI compartment/region, which have none — extraction and chat fail clearly until they're set.

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
