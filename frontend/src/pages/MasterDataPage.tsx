import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { useLanguage } from '../i18n/LanguageContext'
import type { Domain, MasterRecordSearchResult } from '../types/api'

const PAGE_SIZE = 50

export function MasterDataPage() {
  const { domain } = useParams<{ domain: Domain }>()
  const { t } = useLanguage()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<MasterRecordSearchResult[] | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  function runSearch(q: string) {
    if (!domain) return
    setError(null)
    setResults(null)
    api
      .searchMasterRecords(domain, q, { offset: 0, limit: PAGE_SIZE })
      .then((response) => {
        setResults(response.results)
        setHasMore(response.has_more)
      })
      .catch(setError)
  }

  useEffect(() => {
    runSearch(query)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain])

  async function loadMore() {
    if (!domain || results === null) return
    setLoadingMore(true)
    setError(null)
    try {
      const response = await api.searchMasterRecords(domain, query, { offset: results.length, limit: PAGE_SIZE })
      setResults([...results, ...response.results])
      setHasMore(response.has_more)
    } catch (err) {
      setError(err)
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <div>
      <h1>{t('masterData.title', { domain: domain ? t(`domain.${domain}`) : '' })}</h1>
      <form
        className="audit-filter-form"
        onSubmit={(e) => {
          e.preventDefault()
          runSearch(query)
        }}
      >
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('masterData.searchPlaceholder')} />
        <button type="submit">{t('review.search')}</button>
      </form>

      <ErrorBanner error={error} />
      {results === null && !error && <p>{t('common.loading')}</p>}
      {results !== null && results.length === 0 && <p>{t('masterData.empty')}</p>}
      {results !== null && results.length > 0 && (
        <>
          <table className="queue-table">
            <thead>
              <tr>
                <th>{t('masterData.colKey')}</th>
                <th>{t('masterData.colPreview')}</th>
                <th>{t('masterData.colVersion')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {results.map((record) => (
                <tr key={record.id}>
                  <td className="mono">{record.record_key}</td>
                  <td>{Object.values(record.fields).filter(Boolean).slice(0, 3).join(' · ')}</td>
                  <td>{record.version}</td>
                  <td>
                    <Link to={`/master-data/${domain}/${record.id}`}>{t('masterData.view')}</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore && (
            <div className="upload-result-actions">
              <button type="button" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? t('common.loading') : t('masterData.loadMore')}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
