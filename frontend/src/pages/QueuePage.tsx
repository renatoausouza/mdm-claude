import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useLanguage } from '../i18n/LanguageContext'
import { type Domain, type JobStatus, type JobSummary } from '../types/api'

const STATUS_FILTERS: { labelKey: string; value: JobStatus | 'all' }[] = [
  { labelKey: 'queue.filterNeedsReview', value: 'pending_review' },
  { labelKey: 'queue.filterNeedsInfo', value: 'needs_info' },
  { labelKey: 'queue.filterApproved', value: 'approved' },
  { labelKey: 'queue.filterRejected', value: 'rejected' },
  { labelKey: 'queue.filterAll', value: 'all' },
]

export function QueuePage() {
  const { domain } = useParams<{ domain: Domain }>()
  const { t } = useLanguage()
  const [statusFilter, setStatusFilter] = useState<JobStatus | 'all'>('pending_review')
  const [jobs, setJobs] = useState<JobSummary[] | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (!domain) return
    let stale = false
    setJobs(null)
    setError(null)
    api
      .listJobs({ domain, status: statusFilter === 'all' ? undefined : statusFilter })
      .then((response) => {
        // A faster later request (e.g. switching domain twice quickly) may
        // already have resolved and set state by the time this one lands —
        // applying it anyway would show jobs for the wrong domain/filter.
        if (!stale) {
          setJobs(response.jobs)
          setHasMore(response.has_more)
        }
      })
      .catch((err) => {
        if (!stale) setError(err)
      })
    return () => {
      stale = true
    }
  }, [domain, statusFilter])

  return (
    <div>
      <h1>{t('queue.title', { domain: domain ? t(`domain.${domain}`) : '' })}</h1>
      <div className="queue-filters">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            className={statusFilter === filter.value ? 'filter-active' : ''}
            onClick={() => setStatusFilter(filter.value)}
          >
            {t(filter.labelKey)}
          </button>
        ))}
      </div>
      <ErrorBanner error={error} />
      {hasMore && <p className="banner banner-info">{t('queue.truncatedNotice')}</p>}
      {jobs === null && !error && <p>{t('common.loading')}</p>}
      {jobs !== null && jobs.length === 0 && <p>{t('queue.empty')}</p>}
      {jobs !== null && jobs.length > 0 && (
        <table className="queue-table">
          <thead>
            <tr>
              <th>{t('queue.colStatus')}</th>
              <th>{t('queue.colCreated')}</th>
              <th>{t('queue.colSubmittedBy')}</th>
              <th>{t('queue.colDuplicate')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>
                  <StatusBadge status={job.status} />
                </td>
                <td>{new Date(job.created_at).toLocaleString()}</td>
                <td>{job.uploaded_by ?? t('common.none')}</td>
                <td>{job.duplicate_review_case_id ? t('common.yes') : t('common.none')}</td>
                <td>
                  <Link to={`/job/${job.id}`}>{t('queue.review')}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
