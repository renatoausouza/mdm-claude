import { useEffect, useState } from 'react'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { useLanguage } from '../i18n/LanguageContext'
import type { DashboardResponse } from '../types/api'

export function DashboardPage() {
  const { t } = useLanguage()
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    api.getDashboard().then(setDashboard).catch(setError)
  }, [])

  if (error) return <ErrorBanner error={error} />
  if (!dashboard) return <p>{t('common.loading')}</p>

  // Every status that appears for at least one domain, in a stable order —
  // the pipeline table's columns, so a status only Supplier ever hits
  // still gets a column (showing 0) for Client/Product rather than the
  // table silently having a different shape per domain.
  const statuses = [...new Set(dashboard.pipeline_health.flatMap((row) => Object.keys(row.status_counts)))]

  return (
    <div>
      <h1>{t('dashboard.title')}</h1>

      <section className="candidate-fields">
        <h2>{t('dashboard.dataHealthTitle')}</h2>
        <table className="queue-table">
          <thead>
            <tr>
              <th>{t('dashboard.colDomain')}</th>
              <th>{t('dashboard.colRecords')}</th>
              <th>{t('dashboard.colCompleteness')}</th>
              <th>{t('dashboard.colCompliance')}</th>
            </tr>
          </thead>
          <tbody>
            {dashboard.data_quality.map((row) => (
              <tr key={row.domain}>
                <td>{t(`domain.${row.domain}`)}</td>
                <td>{row.record_count}</td>
                <td>{row.record_count === 0 ? t('dashboard.noRecordsYet') : `${Math.round(row.completeness * 100)}%`}</td>
                <td>{row.record_count === 0 ? t('dashboard.noRecordsYet') : `${Math.round(row.compliance * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="candidate-fields">
        <h2>{t('dashboard.pipelineTitle')}</h2>
        <table className="queue-table">
          <thead>
            <tr>
              <th>{t('dashboard.colDomain')}</th>
              {statuses.map((status) => (
                <th key={status}>{t(`status.${status}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dashboard.pipeline_health.map((row) => (
              <tr key={row.domain}>
                <td>{t(`domain.${row.domain}`)}</td>
                {statuses.map((status) => (
                  <td key={status}>{row.status_counts[status] ?? 0}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="field-hint">
          {t('dashboard.extractionFailureRate', { rate: Math.round(dashboard.extraction_failure_rate * 100) })}
          {' · '}
          {t('dashboard.openDuplicateCases', { count: dashboard.open_duplicate_case_count })}
        </p>
      </section>
    </div>
  )
}
