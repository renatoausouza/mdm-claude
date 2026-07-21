import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../auth/AuthContext'
import { useLanguage } from '../i18n/LanguageContext'
import { useReviewAction } from '../hooks/useReviewAction'
import type { MasterRecordEditRequestResponse } from '../types/api'

export function EditRequestResolvePage() {
  const { requestId } = useParams<{ requestId: string }>()
  const { session } = useAuth()
  const { t } = useLanguage()
  const [editRequest, setEditRequest] = useState<MasterRecordEditRequestResponse | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [notes, setNotes] = useState('')
  const { busy, actionError, message, run } = useReviewAction()

  const load = useCallback(() => {
    if (!requestId) return
    setLoadError(null)
    api.getEditRequest(requestId).then(setEditRequest).catch(setLoadError)
  }, [requestId])

  useEffect(() => {
    load()
  }, [load])

  if (loadError) return <ErrorBanner error={loadError} />
  if (!editRequest) return <p>{t('common.loading')}</p>

  const isApprover = session?.role === 'approver'
  const isPending = editRequest.status === 'pending'
  const isOwnRequest = editRequest.submitted_by === session?.userId

  function resolve(decision: 'approve' | 'reject') {
    run(() => api.resolveEditRequest(requestId!, decision, notes || undefined), 'common.editRequest', load)
  }

  return (
    <div>
      <h1>
        {t('editRequest.title')} <StatusBadge status={editRequest.status} />
      </h1>

      <table className="comparison-table">
        <thead>
          <tr>
            <th>{t('duplicate.colField')}</th>
            <th>{t('duplicate.colExisting')}</th>
            <th>{t('duplicate.colNew')}</th>
          </tr>
        </thead>
        <tbody>
          {editRequest.comparisons.map((comparison) => (
            <tr key={comparison.field} className={comparison.differs ? 'comparison-differs' : ''}>
              <td>{t(`field.${comparison.field}`)}</td>
              <td>{comparison.old_value ?? t('common.none')}</td>
              <td>{comparison.new_value ?? t('common.none')}</td>
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
          {isOwnRequest && <p className="banner banner-info">{t('editRequest.segregationBanner')}</p>}
          <ErrorBanner error={actionError} />
          {message && <p className="banner banner-success">{message}</p>}
          <div className="review-action-buttons">
            <button
              type="button"
              className="btn-primary btn-stamp"
              onClick={() => resolve('approve')}
              disabled={busy || isOwnRequest}
              title={isOwnRequest ? t('editRequest.segregationTitle') : undefined}
            >
              {t('review.approve')}
            </button>
            <button type="button" className="btn-danger" onClick={() => resolve('reject')} disabled={busy}>
              {t('duplicate.reject')}
            </button>
          </div>
        </section>
      )}

      {isPending && !isApprover && <p className="field-hint">{t('editRequest.approverOnlyHint')}</p>}
    </div>
  )
}
