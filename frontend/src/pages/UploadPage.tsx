import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import type { Domain, JobResponse } from '../types/api'
import { DOMAIN_LABELS, DOMAINS } from '../types/api'
import { humanize } from '../utils'

export function UploadPage() {
  const navigate = useNavigate()
  const [domain, setDomain] = useState<Domain>('supplier')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<JobResponse | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setError(null)
    setResult(null)
    setSubmitting(true)
    try {
      const response = await api.uploadDocument(file, domain)
      setResult(response)
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <h1>Upload a document</h1>
      <form onSubmit={handleSubmit} className="upload-form">
        <label>
          Domain
          <select value={domain} onChange={(e) => setDomain(e.target.value as Domain)}>
            {DOMAINS.map((d) => (
              <option key={d} value={d}>
                {DOMAIN_LABELS[d]}
              </option>
            ))}
          </select>
        </label>
        <label>
          File
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" disabled={submitting || !file}>
          {submitting ? 'Uploading and extracting…' : 'Upload'}
        </button>
      </form>

      {result && (
        <div className="upload-result">
          <h2>Job created</h2>
          <p>
            Status: <strong>{humanize(result.status)}</strong>
          </p>
          {result.duplicate_review_case_id && (
            <p>A matching record was found — this candidate needs duplicate review.</p>
          )}
          <div className="upload-result-actions">
            <button type="button" onClick={() => navigate(`/job/${result.id}`)}>
              View job
            </button>
            <button
              type="button"
              onClick={() => {
                setResult(null)
                setFile(null)
              }}
            >
              Upload another
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
