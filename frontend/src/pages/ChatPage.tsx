import { useState } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { useLanguage } from '../i18n/LanguageContext'
import type { ChatQueryResponse } from '../types/api'

export function ChatPage() {
  const { t } = useLanguage()
  const [question, setQuestion] = useState('')
  const [response, setResponse] = useState<ChatQueryResponse | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(false)

  async function runQuery(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    setResponse(null)
    try {
      const result = await api.chatQuery(question.trim())
      setResponse(result)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1>{t('chat.title')}</h1>
      <p className="page-intro">{t('chat.intro')}</p>
      <form className="audit-filter-form" onSubmit={runQuery}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('chat.placeholder')}
        />
        <button type="submit" disabled={loading}>
          {loading ? t('common.loading') : t('chat.ask')}
        </button>
      </form>

      <ErrorBanner error={error} />

      {response && !response.understood && <p>{t('chat.notUnderstood')}</p>}

      {response && response.understood && (
        <>
          <p className="chat-filter-summary">
            {t('chat.filterSummary', {
              domain: response.filter_domain ? t(`domain.${response.filter_domain}`) : '',
              contains: response.filter_contains ?? '',
            })}
          </p>
          {response.results.length === 0 && <p>{t('masterData.empty')}</p>}
          {response.results.length > 0 && (
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
                {response.results.map((record) => (
                  <tr key={record.id}>
                    <td className="mono">{record.record_key}</td>
                    <td>{Object.values(record.fields).filter(Boolean).slice(0, 3).join(' · ')}</td>
                    <td>{record.version}</td>
                    <td>
                      <Link to={`/master-data/${record.domain}/${record.id}`}>{t('masterData.view')}</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  )
}
