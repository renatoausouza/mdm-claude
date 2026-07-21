import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'
import { LanguageToggle } from '../components/LanguageToggle'
import { useLanguage } from '../i18n/LanguageContext'

// Enroll then verify — auth.py never issues a full session from the
// enrollment token itself; on success the user is sent back to /login to
// authenticate again with a TOTP code.
export function MfaEnrollPage() {
  const { enrollmentToken, enrollmentUsername, completeMfaEnrollment } = useAuth()
  const { t } = useLanguage()
  const navigate = useNavigate()
  const [secret, setSecret] = useState<string | null>(null)
  const [provisioningUri, setProvisioningUri] = useState<string | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [verifying, setVerifying] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!enrollmentToken) return
    api
      .enrollMfa()
      .then((response) => {
        setSecret(response.secret)
        setProvisioningUri(response.provisioning_uri)
      })
      .catch(setError)
  }, [enrollmentToken])

  if (!enrollmentToken) {
    return <Navigate to="/login" replace />
  }

  async function handleVerify(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setVerifying(true)
    try {
      await api.verifyMfa(totpCode)
      setDone(true)
    } catch (err) {
      setError(err)
    } finally {
      setVerifying(false)
    }
  }

  function handleContinue() {
    completeMfaEnrollment()
    navigate('/login')
  }

  if (done) {
    return (
      <div className="centered-form">
        <LanguageToggle className="pre-auth-language-toggle" />
        <h1>{t('mfaEnroll.doneTitle')}</h1>
        <p>{t('mfaEnroll.doneBody')}</p>
        <button type="button" className="btn-primary" onClick={handleContinue}>
          {t('mfaEnroll.goToSignIn')}
        </button>
      </div>
    )
  }

  return (
    <div className="centered-form">
      <LanguageToggle className="pre-auth-language-toggle" />
      <h1>{t('mfaEnroll.title')}</h1>
      <p>
        {t('mfaEnroll.introPrefix')}
        <strong>{enrollmentUsername}</strong>
        {t('mfaEnroll.introSuffix')}
      </p>
      {provisioningUri && (
        <div className="mfa-qr">
          <QRCodeSVG value={provisioningUri} size={200} />
        </div>
      )}
      {secret && (
        <p className="field-hint">
          {t('mfaEnroll.manualCodePrefix')}
          <code>{secret}</code>
        </p>
      )}
      <form onSubmit={handleVerify}>
        <label>
          {t('mfaEnroll.codeLabel')}
          <input
            value={totpCode}
            onChange={(e) => setTotpCode(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            required
          />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" className="btn-primary" disabled={verifying || !secret}>
          {verifying ? t('mfaEnroll.verifying') : t('mfaEnroll.confirm')}
        </button>
      </form>
    </div>
  )
}
