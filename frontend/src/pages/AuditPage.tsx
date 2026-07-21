import { useEffect, useState } from 'react'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { useLanguage } from '../i18n/LanguageContext'
import type { AuditLogEntryResponse } from '../types/api'

export function AuditPage() {
  const { t } = useLanguage()
  const [documentIdFilter, setDocumentIdFilter] = useState('')
  const [entries, setEntries] = useState<AuditLogEntryResponse[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  function load(documentId?: string) {
    setError(null)
    setEntries(null)
    api
      .listAuditLog(documentId || undefined)
      .then((response) => setEntries(response.entries))
      .catch(setError)
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div>
      <h1>{t('audit.title')}</h1>
      <form
        className="audit-filter-form"
        onSubmit={(e) => {
          e.preventDefault()
          load(documentIdFilter)
        }}
      >
        <input
          value={documentIdFilter}
          onChange={(e) => setDocumentIdFilter(e.target.value)}
          placeholder={t('audit.filterPlaceholder')}
        />
        <button type="submit">{t('audit.filter')}</button>
      </form>

      <ErrorBanner error={error} />
      {entries === null && !error && <p>{t('common.loading')}</p>}
      {entries !== null && (
        <table className="audit-table">
          <thead>
            <tr>
              <th>{t('audit.colWhen')}</th>
              <th>{t('audit.colAction')}</th>
              <th>{t('audit.colDocument')}</th>
              <th>{t('audit.colActor')}</th>
              <th>{t('audit.colDetail')}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td>{new Date(entry.occurred_at).toLocaleString()}</td>
                {/* action is a closed, fixed vocabulary (submitted/approved/...)
                    so it's translated for display; detail is free text
                    written once at event time and stays exactly as recorded
                    — see mdm/i18n.py's own comment on this same split. */}
                <td>{t(`auditAction.${entry.action}`)}</td>
                <td>
                  <code>{entry.document_id}</code>
                </td>
                <td>{entry.actor_user_id ?? t('audit.system')}</td>
                <td>
                  {entry.detail}
                  {(entry.before_json || entry.after_json) && (
                    <details>
                      <summary>{t('audit.changes')}</summary>
                      {entry.before_json && <div>{t('audit.before', { value: entry.before_json })}</div>}
                      {entry.after_json && <div>{t('audit.after', { value: entry.after_json })}</div>}
                    </details>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
