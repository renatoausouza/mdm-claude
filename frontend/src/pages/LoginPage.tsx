import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ErrorBanner } from '../components/ErrorBanner'
import { LanguageToggle } from '../components/LanguageToggle'
import { useLanguage } from '../i18n/LanguageContext'

export function LoginPage() {
  const { session, login } = useAuth()
  const { t } = useLanguage()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  if (session) {
    const redirectTo = (location.state as { from?: string } | null)?.from ?? '/'
    return <Navigate to={redirectTo} replace />
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const result = await login(username, password, totpCode || undefined)
      if (result.mfaEnrollmentRequired) {
        navigate('/mfa-enroll')
      } else {
        navigate('/')
      }
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="centered-form">
      <LanguageToggle className="pre-auth-language-toggle" />
      <h1>{t('login.title')}</h1>
      <form onSubmit={handleSubmit}>
        <label>
          {t('login.username')}
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          {t('login.password')}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label>
          {t('login.authenticatorCode')}
          <span className="field-hint">{t('login.authenticatorHint')}</span>
          <input
            value={totpCode}
            onChange={(e) => setTotpCode(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
          />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting ? t('login.submitting') : t('login.submit')}
        </button>
      </form>
    </div>
  )
}
