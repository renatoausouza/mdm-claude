import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { ProgressBar } from '../components/ProgressBar'
import { StatusBadge } from '../components/StatusBadge'
import { useLanguage } from '../i18n/LanguageContext'
import { type JobResponse } from '../types/api'

export function UploadPage() {
  const { t } = useLanguage()
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
      <h1>{t('upload.title')}</h1>
      <p>{t('upload.intro')}</p>
      <form onSubmit={handleSubmit} className="upload-form">
        <label>
          {t('upload.file')}
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" className="btn-primary" disabled={submitting || !file}>
          {submitting ? t('upload.submitting') : t('upload.submit')}
        </button>
        {submitting && <ProgressBar label={t('upload.progressLabel')} />}
      </form>

      {result && (
        <div className="upload-result">
          <h2>{t('upload.resultsTitle')}</h2>
          <table className="queue-table">
            <thead>
              <tr>
                <th>{t('upload.colDomain')}</th>
                <th>{t('upload.colStatus')}</th>
                <th>{t('upload.colDuplicate')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {result.all_jobs.map((job) => (
                <tr key={job.id}>
                  <td>{t(`domain.${job.domain}`)}</td>
                  <td>
                    <StatusBadge status={job.status} />
                  </td>
                  <td>{job.duplicate_review_case_id ? t('common.yes') : t('common.none')}</td>
                  <td>
                    <Link to={`/job/${job.id}`}>{t('upload.viewJob')}</Link>
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
              {t('upload.another')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
