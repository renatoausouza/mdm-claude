import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../auth/AuthContext'
import { useLanguage } from '../i18n/LanguageContext'
import { useReviewAction } from '../hooks/useReviewAction'
import { REQUIRES_SEGREGATION, type DuplicateCaseResponse, type ResolveDecision } from '../types/api'

export function DuplicateResolvePage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { session } = useAuth()
  const { t } = useLanguage()
  const [duplicateCase, setDuplicateCase] = useState<DuplicateCaseResponse | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set())
  const [notes, setNotes] = useState('')
  const { busy, actionError, message, run } = useReviewAction()

  const load = useCallback(() => {
    if (!caseId) return
    setLoadError(null)
    api.getDuplicateCase(caseId).then(setDuplicateCase).catch(setLoadError)
  }, [caseId])

  useEffect(() => {
    load()
  }, [load])

  if (loadError) return <ErrorBanner error={loadError} />
  if (!duplicateCase) return <p>{t('common.loading')}</p>

  const isApprover = session?.role === 'approver'
  const isPending = duplicateCase.status === 'pending'
  const differingFields = duplicateCase.comparisons.filter((c) => c.differs)
  // reject_all is exempt server-side (duplicates.py's resolve_duplicate) —
  // it doesn't touch the master record, so it isn't a fraud vector the way
  // accepting your own submission's update would be. Only gate accepts.
  const blockedBySegregation =
    REQUIRES_SEGREGATION[duplicateCase.domain] &&
    duplicateCase.uploaded_by !== null &&
    duplicateCase.uploaded_by === session?.userId

  function toggleField(field: string) {
    setSelectedFields((prev) => {
      const next = new Set(prev)
      if (next.has(field)) next.delete(field)
      else next.add(field)
      return next
    })
  }

  function resolve(decision: ResolveDecision) {
    run(
      () =>
        api.resolveDuplicate(caseId!, {
          decision,
          accepted_fields: decision === 'partial' ? Array.from(selectedFields) : undefined,
          notes: notes || undefined,
        }),
      'common.case',
      load,
    )
  }

  return (
    <div>
      <h1>
        {t('duplicate.title')} <StatusBadge status={duplicateCase.status} />
      </h1>
      <p className="field-hint">
        {t('duplicate.matchedOn', {
          key: duplicateCase.match_key === 'manual' ? t('duplicate.matchedOnManual') : duplicateCase.match_key,
        })}
      </p>

      <table className="comparison-table">
        <thead>
          <tr>
            <th>{t('duplicate.colField')}</th>
            <th>{t('duplicate.colExisting')}</th>
            <th>{t('duplicate.colNew')}</th>
            {isPending && <th>{t('duplicate.colAccept')}</th>}
          </tr>
        </thead>
        <tbody>
          {duplicateCase.comparisons.map((comparison) => (
            <tr key={comparison.field} className={comparison.differs ? 'comparison-differs' : ''}>
              <td>{t(`field.${comparison.field}`)}</td>
              <td>{comparison.old_value ?? t('common.none')}</td>
              <td>{comparison.new_value ?? t('common.none')}</td>
              {isPending && (
                <td>
                  {comparison.differs && (
                    <input
                      type="checkbox"
                      checked={selectedFields.has(comparison.field)}
                      onChange={() => toggleField(comparison.field)}
                    />
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {isPending && isApprover && (
        <section className="review-actions">
          <label>
            {t('duplicate.notes')}
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </label>
          {blockedBySegregation && (
            <p className="banner banner-info">
              {t('duplicate.segregationBanner', { domain: t(`domain.${duplicateCase.domain}`).toLowerCase() })}
            </p>
          )}
          <ErrorBanner error={actionError} />
          {message && <p className="banner banner-success">{message}</p>}
          <div className="review-action-buttons">
            <button
              type="button"
              className="btn-primary btn-stamp"
              onClick={() => resolve('accept_all')}
              disabled={busy || blockedBySegregation}
              title={blockedBySegregation ? t('duplicate.segregationTitle') : undefined}
            >
              {t('duplicate.acceptAll')}
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => resolve('partial')}
              disabled={busy || selectedFields.size === 0 || blockedBySegregation}
              title={
                blockedBySegregation
                  ? t('duplicate.segregationTitle')
                  : selectedFields.size === 0
                    ? t('duplicate.selectFieldTitle')
                    : undefined
              }
            >
              {differingFields.length > 0
                ? t('duplicate.acceptSelectedCount', { count: selectedFields.size })
                : t('duplicate.acceptSelected')}
            </button>
            <button type="button" className="btn-danger" onClick={() => resolve('reject_all')} disabled={busy}>
              {t('duplicate.reject')}
            </button>
          </div>
        </section>
      )}

      {isPending && !isApprover && <p className="field-hint">{t('duplicate.approverOnlyHint')}</p>}
    </div>
  )
}
