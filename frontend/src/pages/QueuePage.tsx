import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { DOMAIN_LABELS, type Domain, type JobStatus, type JobSummary } from '../types/api'

const STATUS_FILTERS: { label: string; value: JobStatus | 'all' }[] = [
  { label: 'Needs review', value: 'pending_review' },
  { label: 'Needs info', value: 'needs_info' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'All', value: 'all' },
]

export function QueuePage() {
  const { domain } = useParams<{ domain: Domain }>()
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
      <h1>{domain ? DOMAIN_LABELS[domain] : ''} review queue</h1>
      <div className="queue-filters">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            className={statusFilter === filter.value ? 'filter-active' : ''}
            onClick={() => setStatusFilter(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>
      <ErrorBanner error={error} />
      {hasMore && (
        <p className="banner banner-info">
          Showing the most recent 200 matching jobs — older ones aren't shown. Narrow the status filter above to
          see more.
        </p>
      )}
      {jobs === null && !error && <p>Loading…</p>}
      {jobs !== null && jobs.length === 0 && <p>No jobs match this filter.</p>}
      {jobs !== null && jobs.length > 0 && (
        <table className="queue-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Created</th>
              <th>Submitted by</th>
              <th>Duplicate?</th>
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
                <td>{job.uploaded_by ?? '—'}</td>
                <td>{job.duplicate_review_case_id ? 'Yes' : '—'}</td>
                <td>
                  <Link to={`/job/${job.id}`}>Review</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
