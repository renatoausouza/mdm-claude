import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { ProgressBar } from '../components/ProgressBar'
import { StatusBadge } from '../components/StatusBadge'
import { DOMAIN_LABELS, type JobResponse } from '../types/api'

export function UploadPage() {
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
      const response = await api.uploadDocument(file)
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
      <p>Supplier, Client, and Product candidates are all extracted from a single upload.</p>
      <form onSubmit={handleSubmit} className="upload-form">
        <label>
          File
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" disabled={submitting || !file}>
          {submitting ? 'Uploading and extracting…' : 'Upload'}
        </button>
        {submitting && <ProgressBar label="Extracting document — this can take a few minutes…" />}
      </form>

      {result && (
        <div className="upload-result">
          <h2>Extraction results</h2>
          <table className="queue-table">
            <thead>
              <tr>
                <th>Domain</th>
                <th>Status</th>
                <th>Duplicate?</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {result.all_jobs.map((job) => (
                <tr key={job.id}>
                  <td>{DOMAIN_LABELS[job.domain]}</td>
                  <td>
                    <StatusBadge status={job.status} />
                  </td>
                  <td>{job.duplicate_review_case_id ? 'Yes' : '—'}</td>
                  <td>
                    <Link to={`/job/${job.id}`}>View job</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="upload-result-actions">
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
