import { useEffect, useState } from 'react'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import type { AuditLogEntryResponse } from '../types/api'

export function AuditPage() {
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
      <h1>Audit log</h1>
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
          placeholder="Filter by document id…"
        />
        <button type="submit">Filter</button>
      </form>

      <ErrorBanner error={error} />
      {entries === null && !error && <p>Loading…</p>}
      {entries !== null && (
        <table className="audit-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Action</th>
              <th>Document</th>
              <th>Actor</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td>{new Date(entry.occurred_at).toLocaleString()}</td>
                <td>{entry.action}</td>
                <td>
                  <code>{entry.document_id}</code>
                </td>
                <td>{entry.actor_user_id ?? 'system'}</td>
                <td>
                  {entry.detail}
                  {(entry.before_json || entry.after_json) && (
                    <details>
                      <summary>changes</summary>
                      {entry.before_json && <div>before: {entry.before_json}</div>}
                      {entry.after_json && <div>after: {entry.after_json}</div>}
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
