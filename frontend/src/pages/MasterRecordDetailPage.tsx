import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import * as api from '../api/endpoints'
import { useAuth } from '../auth/AuthContext'
import { ErrorBanner } from '../components/ErrorBanner'
import { useLanguage } from '../i18n/LanguageContext'
import { KEY_FIELDS, REQUIRES_SEGREGATION, type MasterRecordDetailResponse } from '../types/api'

export function MasterRecordDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { session } = useAuth()
  const { t, lang } = useLanguage()
  const [record, setRecord] = useState<MasterRecordDetailResponse | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [editing, setEditing] = useState(false)
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!id) return
    setError(null)
    return api.getMasterRecord(id).then(setRecord).catch(setError)
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  if (error) return <ErrorBanner error={error} />
  if (!record) return <p>{t('common.loading')}</p>

  // Client/Product edit immediately; Supplier requires the second-approver
  // edit-request workflow instead (#20) — same REQUIRES_SEGREGATION split
  // as everywhere else in this app. Either way, only one proposal/edit at
  // a time: hide the affordance while a request is already pending.
  const isSegregated = REQUIRES_SEGREGATION[record.domain]
  const canAct = session?.role === 'approver' && !record.pending_edit_request_id
  const keyField = KEY_FIELDS[record.domain]

  const dateFormat = new Intl.DateTimeFormat(lang === 'pt' ? 'pt-BR' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })

  function startEditing() {
    setOverrides({ ...record!.fields })
    setSaveError(null)
    setMessage(null)
    setEditing(true)
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    try {
      const { [keyField]: _omitted, ...fieldOverrides } = overrides
      if (isSegregated) {
        await api.submitEditRequest(record!.id, fieldOverrides)
        await load()
        setMessage(t('masterData.editRequestSubmitted'))
      } else {
        const updated = await api.editMasterRecord(record!.id, fieldOverrides)
        setRecord(updated)
        setMessage(t('masterData.editSuccess'))
      }
      setEditing(false)
    } catch (err) {
      setSaveError(err)
    } finally {
      setSaving(false)
    }
  }

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

      {record.pending_edit_request_id && (
        <div className="banner banner-info">
          {t('masterData.pendingEditBanner')}{' '}
          <Link to={`/edit-request/${record.pending_edit_request_id}`}>{t('masterData.reviewEditRequest')}</Link>
        </div>
      )}

      {message && !editing && <p className="banner banner-success">{message}</p>}

      <section className="candidate-fields">
        <div className="candidate-fields-header">
          <h2>{t('masterData.fieldsTitle')}</h2>
          {canAct && !editing && (
            <button type="button" onClick={startEditing}>
              {isSegregated ? t('masterData.proposeEdit') : t('masterData.edit')}
            </button>
          )}
        </div>

        {!editing &&
          Object.entries(record.fields).map(([name, value]) => (
            <div className="field-display" key={name}>
              <div className="field-label">{t(`field.${name}`)}</div>
              <div className="field-value">{value}</div>
            </div>
          ))}

        {editing && (
          <>
            {Object.keys(record.fields).map((name) =>
              name === keyField ? (
                <div className="field-display" key={name}>
                  <div className="field-label">{t(`field.${name}`)}</div>
                  <div className="field-value">{record!.fields[name]}</div>
                  <div className="field-hint">{t('masterData.keyFieldReadOnlyHint')}</div>
                </div>
              ) : (
                <label key={name}>
                  {t(`field.${name}`)}
                  <input
                    value={overrides[name] ?? ''}
                    onChange={(e) => setOverrides((prev) => ({ ...prev, [name]: e.target.value }))}
                  />
                </label>
              ),
            )}
            <ErrorBanner error={saveError} />
            <div className="review-action-buttons">
              <button type="button" className="btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? t('common.loading') : isSegregated ? t('masterData.proposeEditSubmit') : t('masterData.save')}
              </button>
              <button type="button" onClick={() => setEditing(false)} disabled={saving}>
                {t('masterData.cancel')}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
