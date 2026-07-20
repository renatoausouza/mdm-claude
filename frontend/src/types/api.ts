// Mirrors src/mdm's Pydantic response/request models exactly (field names,
// nullability). Keep in sync by hand — there's no shared schema generation
// between the Python backend and this frontend.

export type Domain = 'supplier' | 'client' | 'product'
export const DOMAINS: Domain[] = ['supplier', 'client', 'product']
export const DOMAIN_LABELS: Record<Domain, string> = { supplier: 'Supplier', client: 'Client', product: 'Product' }

export type UserRole = 'submitter' | 'approver' | 'admin'

export type JobStatus =
  | 'queued'
  | 'pending_review'
  | 'needs_info'
  | 'approved'
  | 'rejected'
  | 'extraction_failed'
  | 'unsupported_format'

export type DuplicateCaseStatus = 'pending' | 'accepted' | 'rejected' | 'partially_accepted'

// ---- auth.ts ----

export interface UserResponse {
  id: string
  username: string
  role: string
}

export interface LoginResponse {
  token: string
  role: string
  user_id: string
  mfa_enrollment_required: boolean
}

export interface MfaEnrollResponse {
  secret: string
  provisioning_uri: string
}

// ---- extraction_schema.ts ----

export interface Provenance {
  source: 'regex' | 'llm' | string
  page: number | null
  bbox: [number, number, number, number] | null
}

export interface FieldValue {
  value: string
  normalized_value: string | null
  confidence: number
  provenance: Provenance
}

export interface RoleEvidenceInfo {
  matched_label: string
  location: string
  // True only when the role was guessed from the party's position on the
  // page (masthead, no label found anywhere) rather than matched from a
  // real label — must be shown distinctly, never presented as if it were
  // an evidenced match.
  inferred: boolean
}

export interface PartyInfo {
  tax_id: FieldValue
  role: string
  role_evidence: RoleEvidenceInfo | null
}

// ---- per-domain candidate result shapes (the `result` field of
// JobResultResponse, once narrowed by `domain`) ----

export interface SupplierCandidateResult {
  cnpj: FieldValue | null
  legal_name: FieldValue | null
  email: FieldValue | null
  telephone: FieldValue | null
  address: FieldValue | null
  parties: PartyInfo[]
}

export interface ClientCandidateResult {
  tax_id: FieldValue | null
  name: FieldValue | null
  email: FieldValue | null
  telephone: FieldValue | null
  address: FieldValue | null
  parties: PartyInfo[]
}

export interface ProductCandidateResult {
  name: FieldValue | null
  sku: FieldValue | null
  ncm: FieldValue | null
  description: FieldValue | null
  price: FieldValue | null
  quantity: FieldValue | null
  discount: FieldValue | null
}

export type CandidateResult = SupplierCandidateResult | ClientCandidateResult | ProductCandidateResult

// Master (registerable) fields per domain — drives which fields the review
// screen renders as "the record", vs. transactional-evidence-only fields
// (Product's price/quantity/discount) that are shown but never submitted.
export const MASTER_FIELDS: Record<Domain, string[]> = {
  supplier: ['cnpj', 'legal_name', 'email', 'telephone', 'address'],
  client: ['tax_id', 'name', 'email', 'telephone', 'address'],
  product: ['name', 'sku', 'ncm', 'description'],
}

export const REQUIRES_SEGREGATION: Record<Domain, boolean> = {
  supplier: true,
  client: false,
  product: false,
}

// ---- scoring.ts ----

export interface ScoringResult {
  completeness: number
  compliance: number
  reliability: 'Excellent' | 'Good' | 'Low'
  missing_required_fields: string[]
  low_confidence_fields: string[]
  requires_review: boolean
}

// ---- documents.ts ----

export interface JobResponse {
  id: string
  document_id: string
  content_hash: string
  domain: Domain
  status: JobStatus
  retention_until: string | null
  duplicate_review_case_id: string | null
  // Every domain (supplier/client/product) is now extracted from a single
  // upload — this carries all of them so the upload result can show all
  // three without a follow-up request. `id`/`status`/etc. above are just
  // the job matching whichever `domain` was requested.
  all_jobs: JobSummary[]
}

export interface JobResultResponse {
  id: string
  document_id: string
  domain: Domain
  status: JobStatus
  result: Record<string, unknown> | null
  error_detail: string | null
  scoring: ScoringResult | null
  duplicate_review_case_id: string | null
  uploaded_by: string | null
}

export interface JobSummary {
  id: string
  document_id: string
  domain: Domain
  status: JobStatus
  created_at: string
  uploaded_by: string | null
  duplicate_review_case_id: string | null
}

export interface JobListResponse {
  jobs: JobSummary[]
  has_more: boolean
}

// ---- review.ts ----

export interface ReviewDecisionRequest {
  notes?: string | null
  field_overrides?: Record<string, string> | null
}

export interface RequestInfoRequest {
  notes: string
}

export interface ReviewDecisionResponse {
  job_id: string
  status: JobStatus
  master_record_id: string | null
}

// ---- duplicates.ts ----

export interface FieldComparison {
  field: string
  old_value: string | null
  new_value: string | null
  new_confidence: number | null
  differs: boolean
}

export interface DuplicateCaseResponse {
  id: string
  extraction_job_id: string
  matched_master_record_id: string
  match_key: string
  status: DuplicateCaseStatus
  comparisons: FieldComparison[]
  domain: Domain
  uploaded_by: string | null
}

export type ResolveDecision = 'accept_all' | 'reject_all' | 'partial'

export interface ResolveDuplicateRequest {
  decision: ResolveDecision
  accepted_fields?: string[] | null
  notes?: string | null
}

export interface ResolveDuplicateResponse {
  case_id: string
  status: DuplicateCaseStatus
  master_record_id: string | null
}

export interface MasterRecordSearchResult {
  id: string
  domain: Domain
  record_key: string
  version: number
  fields: Record<string, string>
}

export interface MasterRecordSearchResponse {
  results: MasterRecordSearchResult[]
}

export interface LinkDuplicateRequest {
  master_record_id: string
  notes?: string | null
}

export interface LinkDuplicateResponse {
  case_id: string
  status: DuplicateCaseStatus
}

// ---- audit.ts ----

export interface AuditLogEntryResponse {
  id: string
  document_id: string
  action: string
  actor_user_id: string | null
  before_json: string | null
  after_json: string | null
  detail: string | null
  occurred_at: string
}

export interface AuditLogListResponse {
  entries: AuditLogEntryResponse[]
}
