import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { FieldDisplay } from '../components/FieldDisplay'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../auth/AuthContext'
import { useLanguage } from '../i18n/LanguageContext'
import { useReviewAction } from '../hooks/useReviewAction'
import {
  MASTER_FIELDS,
  REQUIRES_SEGREGATION,
  type FieldValue,
  type JobResultResponse,
  type MasterRecordSearchResult,
  type PartyInfo,
  type RejectedTaxId,
} from '../types/api'

const PRODUCT_EVIDENCE_FIELDS = ['price', 'quantity', 'discount']

const DECIDABLE_STATUSES = new Set(['pending_review', 'needs_info'])

// The one error_detail documents.py's extraction pipeline actually sets —
// it's written once, at extraction time, into the DB (not regenerated per
// request like an HTTPException), so mdm.i18n can't translate it live; this
// is the frontend-side display translation for that one known value, same
// pattern as the closed status/field/role vocabularies below.
const BACKEND_EXTRACTION_FAILED_DETAIL = 'Extraction failed; see server logs for details'

export function ReviewDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { session } = useAuth()
  const { t } = useLanguage()
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
  if (!job) return <p>{t('common.loading')}</p>

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
      'common.job',
      load,
    )
  }

  function handleReject() {
    run(() => api.rejectJob(jobId!, { notes: notes || undefined }), 'common.job', load)
  }

  function handleRequestInfo() {
    if (!notes.trim()) {
      setActionError(t('review.notesRequired'))
      return
    }
    run(() => api.requestInfo(jobId!, { notes }), 'common.job', load)
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

  const domainLabel = t(`domain.${job.domain}`)

  return (
    <div>
      <h1>
        {t('review.candidateTitle', { domain: domainLabel })} <StatusBadge status={job.status} />
      </h1>

      {job.duplicate_review_case_id && (
        <div className="banner banner-info">
          {t('review.duplicateFoundBanner')}{' '}
          <button type="button" onClick={() => navigate(`/duplicate/${job.duplicate_review_case_id}`)}>
            {t('review.resolveDuplicate')}
          </button>
        </div>
      )}

      {job.error_detail && (
        <div className="banner banner-error">
          {job.error_detail === BACKEND_EXTRACTION_FAILED_DETAIL ? t('backend.extractionFailed') : job.error_detail}
        </div>
      )}

      {job.scoring && (
        <section className="scoring-summary">
          <h2>{t('review.scoringTitle')}</h2>
          <p>
            {t('review.scoringSummary', {
              reliability: t(`reliability.${job.scoring.reliability}`),
              completeness: Math.round(job.scoring.completeness * 100),
              compliance: Math.round(job.scoring.compliance * 100),
            })}
          </p>
          {job.scoring.missing_required_fields.length > 0 && (
            <p className="scoring-warning">
              {t('review.missingRequired', {
                fields: job.scoring.missing_required_fields.map((f) => t(`field.${f}`)).join(', '),
              })}
            </p>
          )}
          {job.scoring.low_confidence_fields.length > 0 && (
            <p className="scoring-warning">
              {t('review.lowConfidence', {
                fields: job.scoring.low_confidence_fields.map((f) => t(`field.${f}`)).join(', '),
              })}
            </p>
          )}
        </section>
      )}

      {Array.isArray(result.rejected_tax_ids) && (result.rejected_tax_ids as RejectedTaxId[]).length > 0 && (
        <div className="banner banner-info">
          <p>{t('review.rejectedTaxIdIntro')}</p>
          <ul>
            {(result.rejected_tax_ids as RejectedTaxId[]).map((rejected, index) => (
              <li key={index}>
                {t('review.rejectedTaxIdItem', {
                  role: t(`partyRole.${rejected.role}`),
                  value: rejected.value,
                })}
              </li>
            ))}
          </ul>
        </div>
      )}

      <section className="candidate-fields">
        <div className="candidate-fields-header">
          <h2>{t('review.fieldsTitle')}</h2>
          {/* "Raw JSON copy" access-scoping was an open decision in
              solution-brief.md §12/§16 — scoped here to approver/admin
              only, matching how every other PII-bearing surface in this
              app (master-record search, audit log) is already gated. */}
          {(session?.role === 'approver' || session?.role === 'admin') && (
            <button type="button" onClick={() => navigator.clipboard.writeText(JSON.stringify(job.result, null, 2))}>
              {t('review.copyRawJson')}
            </button>
          )}
        </div>
        {masterFields.map((name) => (
          <FieldDisplay
            key={name}
            label={t(`field.${name}`)}
            field={fieldValue(name)}
            required={missingRequired.has(name)}
          />
        ))}
      </section>

      {job.domain === 'product' && (
        <section className="candidate-fields candidate-fields-evidence">
          <h2>{t('review.evidenceTitle')}</h2>
          {PRODUCT_EVIDENCE_FIELDS.map((name) => (
            <FieldDisplay key={name} label={t(`field.${name}`)} field={fieldValue(name)} />
          ))}
        </section>
      )}

      {Array.isArray(result.parties) && (result.parties as PartyInfo[]).length > 0 && (
        <section className="candidate-parties">
          <h2>{t('review.partiesTitle')}</h2>
          <ul>
            {(result.parties as PartyInfo[]).map((party, index) => (
              <li key={index}>
                <strong>{t(`partyRole.${party.role}`)}</strong>: {party.tax_id.value}
                {party.role_evidence?.inferred && (
                  <span className="role-evidence-inferred" title={t('review.inferredRoleTitle')}>
                    {t('review.inferredRole')}
                  </span>
                )}
                {party.role_evidence &&
                  !party.role_evidence.inferred &&
                  t('review.matchedRole', { label: party.role_evidence.matched_label })}
              </li>
            ))}
          </ul>
        </section>
      )}

      {isApprover && isDecidable && (
        <section className="review-actions">
          <h2>{t('review.decisionTitle')}</h2>
          <label>
            {t('review.notes')}
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </label>

          {masterFields.filter((name) => !fieldValue(name)).length > 0 && (
            <div className="field-overrides">
              <p className="field-hint">{t('review.overridesHint')}</p>
              {masterFields
                .filter((name) => !fieldValue(name))
                .map((name) => (
                  <label key={name}>
                    {t(`field.${name}`)}
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
              {t('review.segregationApproveBanner', { domain: domainLabel.toLowerCase() })}
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
              title={blockedBySegregation ? t('review.segregationApproveTitle') : undefined}
            >
              {t('review.approve')}
            </button>
            <button type="button" className="btn-danger" onClick={handleReject} disabled={busy}>
              {t('review.reject')}
            </button>
            <button type="button" onClick={handleRequestInfo} disabled={busy}>
              {t('review.requestInfo')}
            </button>
          </div>

          <details open={searchOpen} onToggle={(e) => setSearchOpen((e.target as HTMLDetailsElement).open)}>
            <summary>{t('review.searchSummary', { domain: domainLabel })}</summary>
            <form onSubmit={handleSearch} className="duplicate-search-form">
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('review.searchPlaceholder')}
              />
              <button type="submit" disabled={searching}>
                {t('review.search')}
              </button>
            </form>
            {searchResults !== null && (
              <ul className="duplicate-search-results">
                {searchResults.length === 0 && <li>{t('review.noMatches')}</li>}
                {searchResults.map((record) => (
                  <li key={record.id}>
                    {Object.values(record.fields).filter(Boolean).slice(0, 3).join(' · ') || record.record_key}
                    <button type="button" onClick={() => handleLink(record.id)} disabled={busy}>
                      {t('review.link')}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </details>
        </section>
      )}

      {!isApprover && isDecidable && <p className="field-hint">{t('review.approverOnlyHint')}</p>}
    </div>
  )
}
