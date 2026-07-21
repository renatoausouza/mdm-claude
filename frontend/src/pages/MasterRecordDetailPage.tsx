import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { useLanguage } from '../i18n/LanguageContext'
import type { MasterRecordDetailResponse } from '../types/api'

export function MasterRecordDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { t, lang } = useLanguage()
  const [record, setRecord] = useState<MasterRecordDetailResponse | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(() => {
    if (!id) return
    setError(null)
    api.getMasterRecord(id).then(setRecord).catch(setError)
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  if (error) return <ErrorBanner error={error} />
  if (!record) return <p>{t('common.loading')}</p>

  const dateFormat = new Intl.DateTimeFormat(lang === 'pt' ? 'pt-BR' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })

  return (
    <div>
      <h1>{t('masterData.detailTitle', { domain: t(`domain.${record.domain}`) })}</h1>
      <p className="field-hint">
        {t('masterData.key', { key: record.record_key })} · {t('masterData.version', { version: record.version })}
      </p>
      <p className="field-hint">
        {t('masterData.firstRegistered', { date: dateFormat.format(new Date(record.first_registered_at)) })}
        {' · '}
        {t('masterData.lastUpdated', { date: dateFormat.format(new Date(record.last_updated_at)) })}
      </p>

      <section className="candidate-fields">
        <h2>{t('masterData.fieldsTitle')}</h2>
        {Object.entries(record.fields).map(([name, value]) => (
          <div className="field-display" key={name}>
            <div className="field-label">{t(`field.${name}`)}</div>
            <div className="field-value">{value}</div>
          </div>
        ))}
      </section>
    </div>
  )
}
