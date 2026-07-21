import { request, uploadFile } from './client'
import type {
  AuditLogListResponse,
  DashboardResponse,
  Domain,
  DuplicateCaseResponse,
  JobListResponse,
  JobResponse,
  JobResultResponse,
  JobStatus,
  LinkDuplicateRequest,
  LinkDuplicateResponse,
  LoginResponse,
  MasterRecordDetailResponse,
  MasterRecordSearchResponse,
  MfaEnrollResponse,
  RequestInfoRequest,
  ResolveDuplicateRequest,
  ResolveDuplicateResponse,
  ReviewDecisionRequest,
  ReviewDecisionResponse,
  UserResponse,
  UserRole,
} from '../types/api'

// ---- auth ----

export function createUser(username: string, password: string, role: UserRole): Promise<UserResponse> {
  return request<UserResponse>('/users', { body: { username, password, role } })
}

export function login(username: string, password: string, totpCode?: string): Promise<LoginResponse> {
  return request<LoginResponse>('/auth/login', {
    body: { username, password, totp_code: totpCode || null },
  })
}

export function logout(): Promise<{ status: string }> {
  return request<{ status: string }>('/auth/logout', { method: 'POST' })
}

export function enrollMfa(): Promise<MfaEnrollResponse> {
  return request<MfaEnrollResponse>('/auth/mfa/enroll', { method: 'POST' })
}

export function verifyMfa(totpCode: string): Promise<{ status: string }> {
  return request<{ status: string }>('/auth/mfa/verify', { body: { totp_code: totpCode } })
}

// ---- documents / jobs ----

export function uploadDocument(file: File): Promise<JobResponse> {
  // A single upload now extracts every domain (supplier/client/product) at
  // once — no domain to pick here anymore, see JobResponse.all_jobs.
  const formData = new FormData()
  formData.append('file', file)
  return uploadFile<JobResponse>('/documents', formData)
}

export function listJobs(filters: { domain?: Domain; status?: JobStatus } = {}): Promise<JobListResponse> {
  return request<JobListResponse>('/jobs', { params: { domain: filters.domain, status: filters.status } })
}

export function getJobResult(jobId: string): Promise<JobResultResponse> {
  return request<JobResultResponse>(`/jobs/${jobId}/result`)
}

// ---- review decisions ----

export function approveJob(jobId: string, payload: ReviewDecisionRequest = {}): Promise<ReviewDecisionResponse> {
  return request<ReviewDecisionResponse>(`/jobs/${jobId}/approve`, { body: payload })
}

export function rejectJob(jobId: string, payload: ReviewDecisionRequest = {}): Promise<ReviewDecisionResponse> {
  return request<ReviewDecisionResponse>(`/jobs/${jobId}/reject`, { body: payload })
}

export function requestInfo(jobId: string, payload: RequestInfoRequest): Promise<ReviewDecisionResponse> {
  return request<ReviewDecisionResponse>(`/jobs/${jobId}/request-info`, { body: payload })
}

// ---- duplicates ----

export function getDuplicateCase(caseId: string): Promise<DuplicateCaseResponse> {
  return request<DuplicateCaseResponse>(`/duplicates/${caseId}`)
}

export function resolveDuplicate(
  caseId: string,
  payload: ResolveDuplicateRequest,
): Promise<ResolveDuplicateResponse> {
  return request<ResolveDuplicateResponse>(`/duplicates/${caseId}/resolve`, { body: payload })
}

export function searchMasterRecords(
  domain: Domain,
  q: string,
  pagination: { offset?: number; limit?: number } = {},
): Promise<MasterRecordSearchResponse> {
  return request<MasterRecordSearchResponse>('/master-records/search', {
    params: {
      domain,
      q,
      offset: pagination.offset !== undefined ? String(pagination.offset) : undefined,
      limit: pagination.limit !== undefined ? String(pagination.limit) : undefined,
    },
  })
}

export function getMasterRecord(recordId: string): Promise<MasterRecordDetailResponse> {
  return request<MasterRecordDetailResponse>(`/master-records/${recordId}`)
}

export function editMasterRecord(
  recordId: string,
  fieldOverrides: Record<string, string>,
): Promise<MasterRecordDetailResponse> {
  return request<MasterRecordDetailResponse>(`/master-records/${recordId}/edit`, {
    body: { field_overrides: fieldOverrides },
  })
}

export function linkDuplicate(jobId: string, payload: LinkDuplicateRequest): Promise<LinkDuplicateResponse> {
  return request<LinkDuplicateResponse>(`/jobs/${jobId}/link-duplicate`, { body: payload })
}

// ---- dashboard ----

export function getDashboard(): Promise<DashboardResponse> {
  return request<DashboardResponse>('/dashboard')
}

// ---- audit ----

export function listAuditLog(documentId?: string): Promise<AuditLogListResponse> {
  return request<AuditLogListResponse>('/audit', { params: { document_id: documentId } })
}
