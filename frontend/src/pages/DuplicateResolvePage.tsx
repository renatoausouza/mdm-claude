import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../auth/AuthContext'
import { useReviewAction } from '../hooks/useReviewAction'
import { DOMAIN_LABELS, REQUIRES_SEGREGATION, type DuplicateCaseResponse, type ResolveDecision } from '../types/api'
import { humanize } from '../utils'

export function DuplicateResolvePage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { session } = useAuth()
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
  if (!duplicateCase) return <p>Loading…</p>

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
      'Case',
      load,
    )
  }

  return (
    <div>
      <h1>
        Duplicate review <StatusBadge status={duplicateCase.status} />
      </h1>
      <p className="field-hint">Matched on: {duplicateCase.match_key === 'manual' ? 'manually linked by a reviewer' : duplicateCase.match_key}</p>

      <table className="comparison-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Existing value</th>
            <th>New value</th>
            {isPending && <th>Accept this field?</th>}
          </tr>
        </thead>
        <tbody>
          {duplicateCase.comparisons.map((comparison) => (
            <tr key={comparison.field} className={comparison.differs ? 'comparison-differs' : ''}>
              <td>{humanize(comparison.field)}</td>
              <td>{comparison.old_value ?? '—'}</td>
              <td>{comparison.new_value ?? '—'}</td>
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
            Notes
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </label>
          {blockedBySegregation && (
            <p className="banner banner-info">
              You submitted this {DOMAIN_LABELS[duplicateCase.domain].toLowerCase()} candidate — segregation of
              duties means you cannot accept an update to your own submission. You may still reject it, or have
              another approver resolve it.
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
              title={blockedBySegregation ? 'You cannot resolve a duplicate for your own submission' : undefined}
            >
              Accept all
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => resolve('partial')}
              disabled={busy || selectedFields.size === 0 || blockedBySegregation}
              title={
                blockedBySegregation
                  ? 'You cannot resolve a duplicate for your own submission'
                  : selectedFields.size === 0
                    ? 'Select at least one differing field above'
                    : undefined
              }
            >
              Accept selected fields{differingFields.length > 0 ? ` (${selectedFields.size} selected)` : ''}
            </button>
            <button type="button" className="btn-danger" onClick={() => resolve('reject_all')} disabled={busy}>
              Reject
            </button>
          </div>
        </section>
      )}

      {isPending && !isApprover && (
        <p className="field-hint">Only approver accounts can resolve a duplicate review case.</p>
      )}
    </div>
  )
}
