import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { FieldDisplay } from '../components/FieldDisplay'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../auth/AuthContext'
import { useReviewAction } from '../hooks/useReviewAction'
import {
  DOMAIN_LABELS,
  MASTER_FIELDS,
  REQUIRES_SEGREGATION,
  type FieldValue,
  type JobResultResponse,
  type MasterRecordSearchResult,
  type PartyInfo,
} from '../types/api'
import { humanize } from '../utils'

const PRODUCT_EVIDENCE_FIELDS = ['price', 'quantity', 'discount']

const DECIDABLE_STATUSES = new Set(['pending_review', 'needs_info'])

export function ReviewDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { session } = useAuth()
  const [job, setJob] = useState<JobResultResponse | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [notes, setNotes] = useState('')
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const { busy, setBusy, actionError, setActionError, message, run } = useReviewAction()

  // Manual duplicate search
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<MasterRecordSearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)

  const load = useCallback(() => {
    if (!jobId) return
    setLoadError(null)
    api
      .getJobResult(jobId)
      .then(setJob)
      .catch(setLoadError)
  }, [jobId])

  useEffect(() => {
    load()
  }, [load])

  if (loadError) return <ErrorBanner error={loadError} />
  if (!job) return <p>Loading…</p>

  const isApprover = session?.role === 'approver'
  const isDecidable = DECIDABLE_STATUSES.has(job.status) && !job.duplicate_review_case_id
  // Only "Approve" is segregation-gated server-side (review.py's
  // approve_job) — reject/request-info are always allowed, so this must
  // not disable those. See D6/FR-13: submitter cannot approve their own
  // supplier submission.
  const blockedBySegregation =
    REQUIRES_SEGREGATION[job.domain] && job.uploaded_by !== null && job.uploaded_by === session?.userId
  const masterFields = MASTER_FIELDS[job.domain]
  const result = job.result ?? {}
  const missingRequired = new Set(job.scoring?.missing_required_fields ?? [])

  function fieldValue(name: string): FieldValue | null {
    const value = result[name]
    return (value as FieldValue | null) ?? null
  }

  function buildOverridesPayload(): Record<string, string> | undefined {
    const entries = Object.entries(overrides).filter(([, value]) => value.trim() !== '')
    return entries.length > 0 ? Object.fromEntries(entries) : undefined
  }

  function handleApprove() {
    run(
      () => api.approveJob(jobId!, { notes: notes || undefined, field_overrides: buildOverridesPayload() }),
      'Job',
      load,
    )
  }

  function handleReject() {
    run(() => api.rejectJob(jobId!, { notes: notes || undefined }), 'Job', load)
  }

  function handleRequestInfo() {
    if (!notes.trim()) {
      setActionError('Notes are required when requesting more information.')
      return
    }
    run(() => api.requestInfo(jobId!, { notes }), 'Job', load)
  }

  async function handleSearch(event: React.FormEvent) {
    event.preventDefault()
    setSearching(true)
    setActionError(null)
    try {
      const response = await api.searchMasterRecords(job!.domain, searchQuery)
      setSearchResults(response.results)
    } catch (err) {
      setActionError(err)
    } finally {
      setSearching(false)
    }
  }

  async function handleLink(masterRecordId: string) {
    setBusy(true)
    setActionError(null)
    try {
      const response = await api.linkDuplicate(jobId!, { master_record_id: masterRecordId })
      navigate(`/duplicate/${response.case_id}`)
    } catch (err) {
      setActionError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h1>
        {DOMAIN_LABELS[job.domain]} candidate <StatusBadge status={job.status} />
      </h1>

      {job.duplicate_review_case_id && (
        <div className="banner banner-info">
          A matching record was found for this candidate.{' '}
          <button type="button" onClick={() => navigate(`/duplicate/${job.duplicate_review_case_id}`)}>
            Resolve duplicate
          </button>
        </div>
      )}

      {job.error_detail && <div className="banner banner-error">{job.error_detail}</div>}

      {job.scoring && (
        <section className="scoring-summary">
          <h2>Scoring</h2>
          <p>
            Reliability: <strong>{job.scoring.reliability}</strong> · Completeness:{' '}
            {Math.round(job.scoring.completeness * 100)}% · Compliance: {Math.round(job.scoring.compliance * 100)}%
          </p>
          {job.scoring.missing_required_fields.length > 0 && (
            <p className="scoring-warning">Missing required: {job.scoring.missing_required_fields.join(', ')}</p>
          )}
          {job.scoring.low_confidence_fields.length > 0 && (
            <p className="scoring-warning">Low confidence: {job.scoring.low_confidence_fields.join(', ')}</p>
          )}
        </section>
      )}

      <section className="candidate-fields">
        <div className="candidate-fields-header">
          <h2>Extracted fields</h2>
          {/* "Raw JSON copy" access-scoping was an open decision in
              solution-brief.md §12/§16 — scoped here to approver/admin
              only, matching how every other PII-bearing surface in this
              app (master-record search, audit log) is already gated. */}
          {(session?.role === 'approver' || session?.role === 'admin') && (
            <button type="button" onClick={() => navigator.clipboard.writeText(JSON.stringify(job.result, null, 2))}>
              Copy raw JSON
            </button>
          )}
        </div>
        {masterFields.map((name) => (
          <FieldDisplay key={name} label={humanize(name)} field={fieldValue(name)} required={missingRequired.has(name)} />
        ))}
      </section>

      {job.domain === 'product' && (
        <section className="candidate-fields candidate-fields-evidence">
          <h2>Transactional evidence (not part of the registered record)</h2>
          {PRODUCT_EVIDENCE_FIELDS.map((name) => (
            <FieldDisplay key={name} label={name} field={fieldValue(name)} />
          ))}
        </section>
      )}

      {Array.isArray(result.parties) && (result.parties as PartyInfo[]).length > 0 && (
        <section className="candidate-parties">
          <h2>Tagged parties in this document</h2>
          <ul>
            {(result.parties as PartyInfo[]).map((party, index) => (
              <li key={index}>
                <strong>{party.role}</strong>: {party.tax_id.value}
                {party.role_evidence?.inferred && (
                  <span className="role-evidence-inferred" title="Guessed from document position — no label was found; double-check this one">
                    {' '}(inferred from position, not a matched label — please verify)
                  </span>
                )}
                {party.role_evidence && !party.role_evidence.inferred && ` (matched "${party.role_evidence.matched_label}")`}
              </li>
            ))}
          </ul>
        </section>
      )}

      {isApprover && isDecidable && (
        <section className="review-actions">
          <h2>Decision</h2>
          <label>
            Notes
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </label>

          {masterFields.filter((name) => !fieldValue(name)).length > 0 && (
            <div className="field-overrides">
              <p className="field-hint">Assign a value for any field the candidate is missing before approving as new:</p>
              {masterFields
                .filter((name) => !fieldValue(name))
                .map((name) => (
                  <label key={name}>
                    {humanize(name)}
                    <input
                      value={overrides[name] ?? ''}
                      onChange={(e) => setOverrides((prev) => ({ ...prev, [name]: e.target.value }))}
                    />
                  </label>
                ))}
            </div>
          )}

          {blockedBySegregation && (
            <p className="banner banner-info">
              You submitted this {DOMAIN_LABELS[job.domain].toLowerCase()} candidate — segregation of duties means
              you cannot approve your own submission. Reject or request more info, or have another approver review
              it.
            </p>
          )}

          <ErrorBanner error={actionError} />
          {message && <p className="banner banner-success">{message}</p>}

          <div className="review-action-buttons">
            <button
              type="button"
              className="btn-primary btn-stamp"
              onClick={handleApprove}
              disabled={busy || blockedBySegregation}
              title={blockedBySegregation ? 'You cannot approve your own submission for this domain' : undefined}
            >
              Approve
            </button>
            <button type="button" className="btn-danger" onClick={handleReject} disabled={busy}>
              Reject
            </button>
            <button type="button" onClick={handleRequestInfo} disabled={busy}>
              Request info
            </button>
          </div>

          <details open={searchOpen} onToggle={(e) => setSearchOpen((e.target as HTMLDetailsElement).open)}>
            <summary>Search for an existing {DOMAIN_LABELS[job.domain]} to link this candidate to</summary>
            <form onSubmit={handleSearch} className="duplicate-search-form">
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by any extracted field value…"
              />
              <button type="submit" disabled={searching}>
                Search
              </button>
            </form>
            {searchResults !== null && (
              <ul className="duplicate-search-results">
                {searchResults.length === 0 && <li>No matches.</li>}
                {searchResults.map((record) => (
                  <li key={record.id}>
                    {Object.values(record.fields).filter(Boolean).slice(0, 3).join(' · ') || record.record_key}
                    <button type="button" onClick={() => handleLink(record.id)} disabled={busy}>
                      Link
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </details>
        </section>
      )}

      {!isApprover && isDecidable && (
        <p className="field-hint">Only approver accounts can approve, reject, or request more information.</p>
      )}
    </div>
  )
}
