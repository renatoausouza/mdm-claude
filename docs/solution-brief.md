# Master Data Registration Automation — Solution Brief

Status: DRAFT — output of a structured grilling interview (17 decisions, D1–D17). Sections marked **ASSUMED DEFAULT** were not individually interviewed (user elected to fold them into this brief as recommendations rather than continue one-by-one) and need explicit review/override, not silent acceptance.

Repository state at time of writing: **no application code exists yet** (verified by inspection). This entire brief describes a system to be built, not one that exists.

---

## 1. Problem Statement and Business Outcome

Business documents (invoices, purchase orders, correspondence, attachments) arrive in heterogeneous formats and contain the raw material for supplier, client, and product master data — but extracting, verifying, and registering that data manually is slow and error-prone, and doing it automatically without a human check is a fraud and compliance risk (fabricated/altered supplier data is a classic vendor-fraud vector).

**Business outcome:** reduce the manual effort of registering new/updated master data while (a) never auto-registering unverified data, (b) preserving an evidence trail from source document to registered record, and (c) doing all of this without sending PII to external services.

**Explicitly not the outcome:** a fully autonomous registration pipeline. That was considered and rejected (see D2, D14).

---

## 2. Personas, Actors, Responsibilities

| Actor | Responsibilities | Notes |
|---|---|---|
| **Submitter** | Uploads/submits a document for extraction. | Not a privileged role; may be any authenticated user, or an automated ingestion path (e.g., a mail drop) — automated ingestion identity still needs to be attributable for D6's segregation-of-duties check. |
| **Approver / Data Steward** | Reviews extraction candidates and duplicate-match cases; approves, rejects, or requests correction. | Requires MFA (D13). Cannot approve their own supplier submissions or sensitive-field supplier updates (D6) — must be a different user than the submitter for those cases. |
| **System Owner / Admin** | User/role management, retention configuration, purge-job oversight, deployment. | Interim point of contact for privacy matters until a DPO is formally designated (see D8 — this is a stopgap, not a substitute). |
| **Auditor (read-only)** | Inspects audit logs, evidence, and lineage. | May not need a dedicated UI in MVP; read access to logs/audit trail satisfies this. |
| **The LLM (OCI Generative AI, Meta Llama)** | Produces candidate structured text only. | **Not an actor with authority.** Zero tool-calling, zero autonomous state changes, ever (D14). Treated as an untrusted-input processor, not a decision-maker. Runs as a managed cloud call within the operator's own OCI tenancy/compartment, not a local model — see NFR-07. |

---

## 3. In-Scope and Out-of-Scope Capabilities

**In scope (MVP):**
- Multi-format document ingestion: PDF, MSG, JSON, XML, TXT/LOG, images (OCR).
- Hybrid regex + local-LLM structured extraction with label-driven entity-role tagging (D3).
- Every extracted field carries `{value, confidence, provenance}` (D16).
- Persistence of documents (encrypted, retention-windowed — D5), extraction records, and master records (D2).
- Mandatory human approval before anything counts as "registered" (D2).
- Risk-tiered segregation of duties for approval: maker-checker on supplier creation/sensitive-field updates, single-approver elsewhere (D6).
- Mandatory MFA for approver accounts (D13).
- Minimal deterministic duplicate detection: exact-match CPF/CNPJ for supplier/client, exact-match SKU for product (D2, D11) — never fuzzy.
- Duplicate matches always link + flag for human review; no auto-merge, ever (D4).
- Master **Product** record = name, SKU, NCM, description only; price/quantity/discount are transactional evidence, not master fields (D10).
- Content-hash idempotency at ingestion (D17).
- Local authentication (username/password + TOTP MFA) — no external IdP (D12).
- Single-tenant data model (D7).

**Out of scope (deferred, phase 2+ — revisit only with real usage data):**
- Golden-record survivorship/merge rules and source-system precedence.
- Publishing/integration to external systems (ERP, CRM, AP systems, etc.).
- Fuzzy/similarity-based identity resolution of any kind (e.g., no-SKU product matching stays 100% manual — D11).
- Multi-tenant data segregation (D7).
- SSO/external identity-provider integration (D12).
- Price-history/price-list tracking as a first-class concept (D10).
- Any autonomous/auto-approval path, regardless of confidence score (D14, D16 — confidence lays groundwork for this but does not implement it).

---

## 4. Functional Requirements

| ID | Requirement | Source decision |
|---|---|---|
| FR-01 | System shall accept document uploads in PDF, MSG, JSON, XML, TXT/LOG, and common image formats (OCR fallback). | Brief §2 |
| FR-02 | System shall compute a content hash (SHA-256) at ingestion and short-circuit reprocessing of an already-seen hash, linking to the existing job. | D17 |
| FR-03 | System shall run a hybrid regex-candidate + local-LLM extraction pass producing structured candidate fields for Supplier, Client, and Product domains. | Brief §3–4 |
| FR-04 | Every extracted field shall carry a confidence score and a provenance record (page/bounding box/matched snippet/source header as applicable). | D16 |
| FR-05 | Tax-ID candidates (CNPJ/CPF) shall be assigned a role (supplier/client/transporter/intermediary/branch/unknown) based solely on contextual labels near the value; no positional ("first/second") fallback. **Amended (ticket #16, post-MVP):** when a page has no label-based supplier match at all, the topmost unlabeled tax-ID candidate defaults to role=supplier — a narrow, last-resort positional exception for the common real-world case of a masthead-only issuer (no "Emitente"/"Fornecedor" label printed anywhere), made deliberately after confirming against real invoices that the strict label-only rule routed most real suppliers to manual review. This exception must never be indistinguishable from a real label match: its evidence is marked as inferred, not evidenced, so a reviewer can tell the difference. | D3 (amended) |
| FR-06 | Any tax-ID candidate with role = unknown shall be routed to human review before any registration or duplicate-matching step. | D3 |
| FR-07 | System shall compute completeness and compliance scores per §10 below, and derive a reliability tier that is hard-capped at "Low" if any field required-for-registration is missing. | D15 |
| FR-08 | System shall compute a per-field confidence gate: any field below the confidence threshold forces human review regardless of the reliability tier. | D16 |
| FR-09 | System shall perform deterministic duplicate detection: normalized CPF/CNPJ exact match for Supplier/Client; exact SKU match for Product. No fuzzy/similarity matching. | D2, D11 |
| FR-10 | A duplicate match shall never auto-merge or auto-overwrite an existing record; it shall create a linked pending-update case shown side-by-side to a human reviewer. | D4 |
| FR-11 | A Product candidate with no SKU shall never be auto-matched; it is always presented to the reviewer as unlinked, with manual search/link tooling to associate it with an existing product or approve as new. | D11 |
| FR-12 | Nothing may be persisted as a registered/updated master record without an explicit approval action by an authenticated human. | D2 |
| FR-13 | Supplier creation and updates to an existing supplier's contact/address/email/phone fields shall require submitter ≠ approver (segregation of duties). Client and Product approvals may be self-approved by any steward-role user. | D6 |
| FR-14 | Approver accounts shall require TOTP-based MFA for authentication. | D13 |
| FR-15 | The Product master record shall consist of name, SKU/code, NCM, and description only; price, quantity, and discount shall be stored as transactional/evidence data linked to the source document, never as master-record fields. | D10 |
| FR-16 | Source documents shall be retained, encrypted at rest, for a defined period beyond the approval decision, then purged or archived (exact duration: **open — needs business/legal input**, see §20). | D5 |
| FR-17 | The LLM shall have no tool-calling, function-calling, or agentic capability; its output is advisory text/JSON only, consumed exclusively by deterministic application code triggered by explicit human action. | D14 |
| FR-18 | All extracted string values shall be treated as untrusted and output-encoded wherever rendered (dashboard, CLI, "copy raw JSON" feature) to prevent stored-XSS via malicious document content. | D14 (consequence) |
| FR-19 | Every registration-relevant action (submit, approve, reject, link-duplicate, correct) shall be recorded in an append-only audit log with actor, timestamp, and before/after values. | D6, D8, §12/§15 |

---

## 5. Non-Functional Requirements (targets marked ASSUMED DEFAULT need confirmation)

| ID | Requirement | Target | Status |
|---|---|---|---|
| NFR-01 | Extraction turnaround (upload → scored, pending review) for a typical single-page PDF | ≤ 60s p95 on the target OCI VM spec | ASSUMED DEFAULT |
| NFR-02 | Concurrent extraction jobs | Bounded by a queue; OCI Generative AI inference is treated as a rate/quota-limited resource, not infinitely parallel | ASSUMED DEFAULT |
| NFR-03 | Availability of the service during business hours | 99% (single-VM, no HA in MVP — explicitly not a redundant deployment) | ASSUMED DEFAULT |
| NFR-04 | Document/DB encryption at rest | AES-256 or OS-native disk encryption + application-layer encryption for the document store | ASSUMED DEFAULT |
| NFR-05 | TLS in transit | TLS 1.2+ terminated at a reverse proxy in front of the fixed application port | ASSUMED DEFAULT — see §17 (port-selection challenge) |
| NFR-06 | No PII in logs | Structured logs must redact/omit CPF, CNPJ, email, phone, address values; log only record IDs and event types | ASSUMED DEFAULT, must be enforced by test (§18) |
| NFR-07 | No outbound network calls carrying PII to a third party outside the OCI tenancy | **Superseded** — the original design ran extraction against a fully local Ollama model (no egress at all). Extraction and the chat feature (#21) now call OCI Generative AI, so document text and extracted fields do leave the host, over TLS, to a regional OCI GenAI endpoint within the same tenancy/compartment. No PII goes to any party outside that tenancy. Verified allowlist of egress otherwise unchanged (none expected beyond OS package updates and the OCI GenAI endpoint). | Design changed post-MVP; still needs an explicit egress-allowlist test (§12/§18) confirming no *other* unexpected egress exists |
| NFR-08 | False-positive duplicate-link rate | Should be ~0% given deterministic-only matching (D2/D11) by construction; measured against a labeled eval set once available | Target, not yet measured |
| NFR-09 | Manual review rate | Expected to be high initially (D3's strict role-tagging and D11's no-SKU handling both push volume into review) — track and revisit only with real data, not pre-optimized | Expectation, not a target to minimize prematurely |

---

## 6. Data Domains and Canonical Data Model

Core entities (conceptual, not a DB schema yet):

- **Document**: id, content_hash, storage_ref (encrypted), uploaded_by, uploaded_at, retention_until, status (active/purged/archived).
- **ExtractionJob**: id, document_id, status (queued/processing/scored/pending_review/approved/rejected/needs_info), created_at, model_version, prompt_version.
- **ExtractionCandidate** (one per Supplier/Client/Product found in a job): domain (supplier/client/product), fields: `{ [field_name]: { value, confidence, provenance, normalized_value } }`, role (for tax-ID-bearing candidates), completeness_score, compliance_score, reliability_tier.
- **OtherParty**: tax-ID-bearing entities in a document that aren't supplier/client (transporter, intermediary, branch) — role-tagged, retained, never forced into supplier/client slots (D3).
- **MasterRecord** (Supplier | Client | Product): canonical registered record, versioned (each approval creates a new version, prior versions retained for lineage), current fields, first_registered_at, last_updated_at.
- **DuplicateReviewCase**: candidate_id, matched_master_record_id, match_key (CPF/CNPJ/SKU), status (pending/accepted/rejected/partially_accepted), reviewed_by, reviewed_at.
- **ApprovalEvent**: candidate_id or duplicate_review_case_id, submitted_by, approved_by, decision, decided_at, legal_basis_tag (per D9), required-field-hard-floor flag if applicable (D15).
- **AuditLogEntry**: append-only, actor, action, target_entity, before/after snapshot, timestamp.
- **User**: id, credentials (hashed), role(s), mfa_enrollment, active/disabled.

---

## 7. Document-Processing Lifecycle and State Machine

```
Uploaded
  → HashCheck (D17)
      → [duplicate hash found] → Linked to existing Job → (terminal, no new processing)
      → [new hash] → Queued
  → Processing (regex candidates + OCR fallback + LLM extraction)
  → Scored (completeness/compliance/reliability per §10; confidence gate per D16)
  → PendingReview
      → [tax-ID role = unknown, OR confidence below threshold, OR required field missing] → forced into PendingReview regardless of score (D3/D15/D16)
      → [duplicate key match found] → DuplicateReviewCase created, held alongside PendingReview
  → Reviewer decision:
      → Approved → MasterRecord created/updated (new version), ApprovalEvent logged
      → Rejected → terminal, ApprovalEvent logged, no MasterRecord change
      → NeedsInfo → returns to PendingReview with reviewer notes (not a new upload)
  → Document retained per its retention_until (D5) → Purged or Archived
```

---

## 8. Extraction Schema, Evidence, Confidence, Provenance Model

Every field, on every candidate, is a structured object, not a bare value (D16):

```json
{
  "cnpj": {
    "value": "12.345.678/0001-99",
    "normalized_value": "12345678000199",
    "confidence": 0.92,
    "role": "supplier",
    "role_evidence": { "matched_label": "Emitente", "location": "page 1, header block" },
    "provenance": { "source": "pdf_layout", "page": 1, "bbox": [88, 140, 240, 156] }
  }
}
```

- Tax-ID fields additionally carry `role` + `role_evidence` (D3).
- Price/quantity/discount fields (Product domain) are captured the same way but stored as **transactional evidence linked to the document**, never copied into the Product MasterRecord (D10).
- Raw values are always preserved alongside normalized values (never normalize-and-discard) — needed for audit/dispute resolution and to avoid silently masking OCR/extraction errors.

---

## 9. Identity-Resolution and Duplicate-Handling Strategy

- **Supplier/Client**: deterministic exact match on normalized CPF/CNPJ only. No fuzzy matching (D2).
- **Product**: deterministic exact match on SKU only. No SKU present → always unlinked, human-searched (D11). No NCM+name fallback (NCM is a shared tax-classification code, too weak a key — rejected explicitly).
- **On any match**: link + flag for human review, side-by-side diff, human accepts/rejects/partially-accepts fields. No auto-merge, no auto-overwrite, ever (D4).
- **Golden-record survivorship, source-precedence, merge/unmerge**: explicitly out of scope for MVP (D2). Do not build this speculatively.
- **Entity role assignment** (which party is supplier vs. client vs. other): label-driven from contextual text first (D3); **amended by ticket #16** to fall back to a narrow positional default (topmost unlabeled candidate → supplier) only when no label-based supplier match exists anywhere on the page — evidence for this case is explicitly marked "inferred from position," never presented as a matched label. Unknown-role tax IDs (still the outcome whenever neither a label nor this narrow fallback applies) always route to review.

---

## 10. Validation and Quality-Score Formulas (with examples)

**Completeness** = (populated fields) / (total required + optional fields defined for the domain). Denominator is fixed regardless of what's populated.

**Compliance** = (populated fields that pass structural validation) / (populated fields). *(Original formula — retained, but see hard-floor correction below; this metric alone can look high on a sparse-but-valid record, which is why it must never be read in isolation from completeness.)*

**Reliability tier** (corrected per D15):
1. If any field marked *required-for-registration* is missing → **tier = Low**, unconditionally, regardless of the percentages below.
2. Else: Excellent if completeness ≥ 90% AND compliance ≥ 90%; Good if both ≥ 70%; Low otherwise.

**Confidence gate** (D16, independent axis — not part of the tier math): if any field's confidence is below the configured threshold, the candidate is forced into PendingReview regardless of its reliability tier. A "Low reliability" record and a "high reliability but low-confidence" record both land in the review queue, for different, clearly distinguishable reasons.

**Worked example** — Supplier candidate missing CNPJ (required-for-registration), but 9/10 other fields populated and valid:
- Naive old formula: completeness = 90%, compliance = 100% → would read as "Excellent." **This is the exact failure mode D15 fixes.**
- Corrected formula: required field (CNPJ) missing → tier = **Low**, unconditionally, flagged "missing required field: CNPJ."

**Required-for-registration fields** (redefined per D15 — required for the *final registered record*, not for the raw extraction to be valid): Supplier = legal name + CNPJ; Client = name + CPF/CNPJ; Product = name (SKU is not hard-required at extraction time; its absence routes to manual linking per D11, and may be assigned during review).

---

## 11. Human-Review and Approval Workflow

1. Candidate enters PendingReview (from the state machine in §7).
2. Reviewer sees: extracted fields with confidence + provenance highlighted (D16), role assignments with evidence (D3), and any DuplicateReviewCase side-by-side diff (D4).
3. Reviewer actions: Approve / Reject / Request More Info / (for duplicates) Accept-all / Reject-all / Accept-selected-fields.
4. **Segregation of duties enforced at this step**: if the candidate is a Supplier creation or a sensitive-field update to an existing Supplier, the system blocks approval if approver == submitter (D6).
5. MFA re-verification (or session-level MFA already satisfied) required for approver accounts (D13).
6. Every decision writes an ApprovalEvent + AuditLogEntry (immutable).

---

## 12. LGPD Privacy Requirements and Control Mapping

| LGPD concern | Status | Detail |
|---|---|---|
| Data controller | Resolved | The company itself (single-tenant, D7) — no separate controller/operator relationship to model. |
| DPO / privacy contact | **GAP — DECISION NEEDED** | No DPO exists anywhere in the org yet (D8). This is an organizational risk to escalate before production go-live, not something this project resolves. System Owner is an interim contact only. |
| Legal basis | Working assumption, **PENDING LEGAL SIGN-OFF** | Mixed: legitimate interest (Art. 7 IX, needs a documented LIA) for general master-data maintenance; legal/regulatory obligation (Art. 7 II) for fiscally-mandated CNPJ/CPF fields (D9). Data model keeps basis-per-purpose as a tagged, changeable field — not hard-coded — so a legal correction doesn't require a schema rewrite. |
| Purpose limitation / data minimization | Partially addressed | Product schema deliberately excludes price/quantity from master data (D10); tax-ID role tagging avoids capturing unrelated third parties into supplier/client slots (D3). |
| Retention & deletion | Mechanism resolved, duration open | Defined retention window post-approval, then purge/archive (D5). **Duration itself is an open business/legal decision** — may have a statutory floor under Brazilian tax/commercial law independent of LGPD. |
| Data-subject request handling | **NOT YET DESIGNED** | No workflow specified. Flagged as a gap — needs at minimum a manual process (who receives a request, how a record is located/corrected/deleted) even before a DPO is named. |
| Encryption in transit/at rest | ASSUMED DEFAULT | TLS + at-rest encryption for documents and DB (§5, §17). |
| Access control / RBAC | Partially resolved | Submitter/Approver/Admin roles, MFA for approvers (D6, D12, D13). Full permission matrix not yet detailed. |
| PII in logs | ASSUMED DEFAULT control | Must redact CPF/CNPJ/email/phone/address from logs (NFR-06); needs a test asserting this. |
| PII exposure via "raw JSON copy" UI feature | Addressed | Must be output-encoded like any other rendering surface (D14 consequence, FR-18); also worth considering restricting this feature to approver role only, or redacting until approved — **open UI decision, not yet made**. |
| Tenant isolation | N/A | Single-tenant (D7). |
| Offline-first ≠ automatically LGPD-compliant | Explicitly acknowledged | "Runs on our own VM" addresses cross-border/third-party transfer concerns, not consent, purpose limitation, retention, data-subject rights, or accountability — all of which still require the controls above. |

---

## 13. DAMA Governance Mapping and Identified Gaps

What this design covers: **completeness**, a corrected **compliance/validity** measure (D15), a nascent **confidence** dimension (D16), and basic **lineage/provenance** at the field level (D16) plus record versioning (§6).

**Explicitly NOT covered, and not to be claimed as covered:**
- **Accuracy** beyond structural/format validity (a syntactically valid CNPJ is not proven to be the *correct* CNPJ — only human review and, eventually, a labeled evaluation set close this gap, NFR-08).
- **Consistency** across sources (no cross-referencing against an external registry of valid CNPJs, for instance — this is a deliberate scope decision, not a technical limitation of the OCI Generative AI call; this is a real accuracy ceiling, not a solvable gap).
- **Uniqueness** beyond the deterministic-key dedup already described (D2/D11) — no fuzzy/near-duplicate detection.
- **Timeliness** — not modeled at all yet (no SLA on how current a registered record is expected to be).
- **Stewardship ownership** — "Approver" is a role, not a named accountable steward per data domain; not yet designed.
- **Source-system precedence / survivorship** — explicitly deferred (D2).

This system should not be described to stakeholders as "DAMA-DMBOK compliant." It implements a specific, narrow subset of data-quality dimensions, with the gaps above documented, not hidden.

---

## 14. Threat Model and Security Controls

| Threat | Control |
|---|---|
| Prompt injection via malicious document content | LLM output is advisory-only, zero agentic capability (D14) — a successful injection produces a bad suggestion in a review queue, not an autonomous action. |
| Stored XSS via extracted field values (e.g., a "supplier name" containing script content) | Output-encoding required everywhere extracted values render, including the raw-JSON-copy feature (FR-18). |
| Vendor/BEC fraud via fabricated or altered supplier data | Segregation of duties (submitter ≠ approver) on supplier creation and sensitive-field updates (D6); MFA on approver accounts (D13). |
| Compromised approver credentials | MFA required for approvers (D13); local auth must include account lockout/rate-limiting (D12). |
| Malicious upload (malware, decompression bomb, path traversal, oversized file) | **ASSUMED DEFAULT, not yet interviewed in depth**: recommend local antivirus scan (e.g., ClamAV) rather than a cloud AV API — no reason to add a second cloud dependency for raw file content beyond the OCI Generative AI call NFR-07 already accepts for extracted text — plus a hard max-file-size limit, size/ratio checks before decompressing any archive-like content, and storage keyed by generated UUID (never a user-supplied filename) to prevent path traversal. **Needs explicit confirmation**, not silent acceptance. |
| Encrypted/password-protected PDFs | ASSUMED DEFAULT: reject with a clear error routed to manual handling, unless real documents in practice are commonly password-protected (unconfirmed) — **needs a fact-check against real document samples**. |
| PII in logs/error traces/temp files/test fixtures | Required control (NFR-06); test fixtures must use synthetic/redacted data, never real PII (§18). |
| Network egress carrying PII (model calls, package services, backups) | Extraction/chat calls to OCI Generative AI are now a known, deliberate egress path within the operator's own tenancy (NFR-07) — not the risk to verify. The remaining control need is an egress allowlist/audit step confirming no *other*, unexpected egress exists (e.g., package services phoning further than OS updates, no backup path silently including raw documents). |
| Secrets management | ASSUMED DEFAULT: environment-based secrets or a local secrets store, never committed to source control; not yet designed in detail. |

---

## 15. Persistence, Retention, Deletion, and Audit Strategy

- A database is needed — not because it's "technically convenient" but because D2 requires persistence, D4/D6 require a review/approval workflow with state, and D6/D8 require an audit trail. The lifecycle in §7 and the entities in §6 define the actual requirement; database technology choice is an implementation detail to resolve when building starts, not a governance decision.
- Documents: encrypted at rest, retention-windowed per D5 (duration open), scheduled purge/archive job.
- Master records: versioned — every approval creates a new version; prior versions retained for lineage, never hard-deleted (deletion propagation rules for a data-subject erasure request are **not yet designed** — gap, tied to §12's data-subject-request gap).
- Audit log: append-only, covers every FR-19 action.
- Backup/restore: **ASSUMED DEFAULT**, not yet interviewed — needs its own design pass (encrypted backups, restore testing, retention of backups itself subject to the same LGPD minimization question as primary data).

---

## 16. API, UI, and CLI Requirements

Minimum surface (ASSUMED DEFAULT shape, not individually interviewed):

- **API**: `POST /documents` (upload), `GET /jobs/{id}` (status), `GET /jobs/{id}/result` (scored candidate), `POST /jobs/{id}/approve|reject|request-info`, `GET /duplicates/{id}`, `POST /duplicates/{id}/resolve`, `GET /audit` (scoped to auditor/admin), `GET /health`, `GET /metrics`.
- **UI**: MFA-gated login; review queue with confidence/provenance highlighting; duplicate side-by-side diff view; audit history view (at least for admins/auditors); the "raw JSON copy" feature must be reconsidered for access-scoping (open question, §12).
- **CLI**: local extraction for testing/debugging, job status lookup, and server lifecycle management (start/stop under systemd) — mirrors API capabilities for scripting, not a separate feature set.

---

## 17. OCI Deployment and Operations Design

- **Challenge the automatic port-fallback behavior explicitly**: a production service that silently picks a different port when its default is occupied breaks health checks, firewall rules, reverse-proxy upstream config, and systemd unit expectations that all assume a fixed, known port. **Recommendation: fixed port only, fail loudly (refuse to start) if the port is unavailable, rather than silently rebinding.**
- Reverse proxy (e.g., Nginx/Caddy) terminates TLS in front of the fixed application port; OCI security lists + host firewall (e.g., ufw/firewalld) restrict access to that proxy port only.
- systemd hardening: dedicated non-root service user, `ProtectSystem=strict`, `NoNewPrivileges=yes`, restricted filesystem write paths (document store + DB only), resource limits.
- Health checks: `/health` (liveness) separate from a readiness check that confirms OCI Generative AI is actually reachable/authenticated — a service that's "up" but can't reach the model should not report ready.
- Model/version pinning: pin the OCI Generative AI model ID (`MDM_OCI_GENAI_MODEL_ID`) and the extraction prompt version together (both already tracked per ExtractionJob in §6) so results are reproducible and neither an on-demand model-catalog rotation nor a prompt change silently changes extraction behavior mid-flight.
- Log rotation, monitoring/alerting, backup/restore, and update/rollback strategy: **ASSUMED DEFAULT**, not individually interviewed — standard practice recommended (logrotate or systemd journal limits; alert on job-queue backlog and failed-job rate; tested restore procedure, not just backup existence).

---

## 18. Testing and Evaluation Strategy

- Unit tests: check-digit validation, scoring formulas (including the D15 hard-floor case explicitly), regex candidate extraction, role-tagging logic.
- Prompt-injection test cases: documents crafted to manipulate extraction output — assert they produce only bad *candidates* (caught by review), never bypass the advisory-only boundary (D14).
- Schema/contract tests: malformed LLM JSON output, partial output, hallucinated fields not present in source.
- Security tests: auth (lockout, MFA, session handling), file-upload attacks (§14), output-encoding/XSS on extracted values.
- Privacy tests: assert no PII appears in logs/error traces (NFR-06); test fixtures use synthetic data only, never real PII.
- Integration/E2E: full document → review → approval → registered-record flow, including the duplicate-review path (D4) and segregation-of-duties enforcement (D6).
- Accuracy benchmarking: a labeled evaluation dataset (real-world-shaped but synthetic/redacted documents with known-correct answers) to measure extraction accuracy and calibrate confidence thresholds — **does not exist yet, needs to be built**, and is the only real way to validate NFR-08.
- Deployment smoke tests, backup/restore drill, failure-recovery tests: standard, not yet detailed.

---

## 19. Phased Implementation Roadmap

- **Phase 0 — Foundations**: auth + MFA (D12/D13), DB schema for the entities in §6, document ingestion + hash idempotency (D17), audit logging (FR-19). No extraction yet — prove the workflow skeleton first.
- **Phase 1 — MVP (this brief's scope)**: full hybrid extraction pipeline for Supplier, Client, Product; role tagging (D3); scoring with hard floor (D15) and confidence gate (D16); deterministic dedup + review workflow (D4, D11); segregation-of-duties approval (D6). Ships when Definition of Done (§21) is met.
- **Phase 2 — Deferred, revisit only with real usage data**: golden-record survivorship, external publish/integration, fuzzy identity resolution, price-history tracking, multi-tenant support if ever needed, DPO formally designated and data-subject-request workflow built out.

---

## 20. Risks, Assumptions, Unresolved Decisions, and Recommended Priorities

**Unresolved, needs your/legal input before production go-live (not blocking further design work):**
- Document retention duration (D5) — needs a specific number, possibly bounded below by Brazilian tax/commercial-law retention minimums.
- DPO designation (D8) — organizational gap, escalate to leadership.
- Legal basis sign-off (D9) — current mapping is a working assumption, not a legal opinion.
- Data-subject-request handling workflow (§12) — not designed at all yet.

**ASSUMED DEFAULTS in this brief that need explicit confirmation, not silent acceptance** (per your instruction to fold remaining lower-tier topics in as recommendations rather than interview them individually): file-upload security specifics (§14), async job architecture and concurrency limits (§5 NFR-02), OCI deployment/ops hardening details (§17), backup/restore design (§15), and the full API/UI surface shape (§16).

**Top risk if this brief is misread:** treating any of the above ASSUMED DEFAULTS as decided. They are recommendations, not the outcome of the same grilling rigor applied to D1–D17.

---

## 21. Definition of Done and Acceptance Criteria (MVP)

- [ ] All three domains (Supplier, Client, Product) extract via the hybrid pipeline with role tagging where applicable (D3).
- [ ] Every field carries confidence + provenance (D16); low-confidence and missing-required-field cases are demonstrably forced into review (D15, D16).
- [ ] Deterministic dedup works for CPF/CNPJ (Supplier/Client) and SKU (Product); no-SKU products correctly route to manual linking (D11).
- [ ] Zero path exists by which a record becomes "registered" without an explicit human approval action (D2) — verified by test, not just by design intent.
- [ ] Segregation-of-duties enforcement blocks self-approval on supplier creation/sensitive-field updates (D6) — verified by test.
- [ ] MFA is enforced for all approver accounts (D13) — verified by test.
- [ ] Content-hash idempotency prevents duplicate job creation on resubmission (D17).
- [ ] Prompt-injection test suite passes: injected documents never produce an autonomous state change (D14).
- [ ] No real PII appears in logs, error traces, or test fixtures (NFR-06).
- [ ] Retention/purge job runs on schedule against the (eventually specified) retention window (D5).
- [ ] This brief's ASSUMED DEFAULT sections have each been explicitly reviewed and either confirmed or revised — not carried forward silently into production.
