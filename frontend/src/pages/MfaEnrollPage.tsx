import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import * as api from '../api/endpoints'
import { ErrorBanner } from '../components/ErrorBanner'

// Enroll then verify — auth.py never issues a full session from the
// enrollment token itself; on success the user is sent back to /login to
// authenticate again with a TOTP code.
export function MfaEnrollPage() {
  const { enrollmentToken, enrollmentUsername, completeMfaEnrollment } = useAuth()
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
        <h1>Two-factor authentication enabled</h1>
        <p>Sign in again with your username, password, and a current authenticator code.</p>
        <button type="button" onClick={handleContinue}>
          Go to sign in
        </button>
      </div>
    )
  }

  return (
    <div className="centered-form">
      <h1>Set up two-factor authentication</h1>
      <p>
        Approver account <strong>{enrollmentUsername}</strong> requires an authenticator app before it can be used.
      </p>
      {provisioningUri && (
        <div className="mfa-qr">
          <QRCodeSVG value={provisioningUri} size={200} />
        </div>
      )}
      {secret && (
        <p className="field-hint">
          Or enter this code manually: <code>{secret}</code>
        </p>
      )}
      <form onSubmit={handleVerify}>
        <label>
          Enter the 6-digit code from your authenticator app
          <input
            value={totpCode}
            onChange={(e) => setTotpCode(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            required
          />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" disabled={verifying || !secret}>
          {verifying ? 'Verifying…' : 'Confirm'}
        </button>
      </form>
    </div>
  )
}
