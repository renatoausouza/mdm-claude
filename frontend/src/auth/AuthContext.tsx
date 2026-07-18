import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { setAuthToken, setUnauthorizedHandler } from '../api/client'
import * as api from '../api/endpoints'
import type { UserRole } from '../types/api'

interface Session {
  token: string
  role: UserRole
  username: string
  userId: string
}

interface AuthContextValue {
  session: Session | null
  // A separate, narrower-scoped token issued mid-login to an approver who
  // hasn't finished MFA enrollment yet (auth.py's "mfa_enrollment" session
  // scope) — deliberately NOT part of `session` (the user isn't logged in
  // until enrollment completes and they log in again with a TOTP code).
  enrollmentToken: string | null
  enrollmentUsername: string | null
  login: (username: string, password: string, totpCode?: string) => Promise<{ mfaEnrollmentRequired: boolean }>
  completeMfaEnrollment: () => void
  logout: () => Promise<void>
}

const STORAGE_KEY = 'mdm.session'

const AuthContext = createContext<AuthContextValue | null>(null)

function loadStoredSession(): Session | null {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Session
  } catch {
    return null
  }
}

// Set the API client's token synchronously at module load, before React
// starts rendering. On a hard page reload, child components' own data-fetch
// effects can fire before AuthProvider's useEffect below (child effects run
// before parent effects), which would otherwise send the first request with
// no Authorization header even though a session exists.
setAuthToken(loadStoredSession()?.token ?? null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadStoredSession)
  const [enrollmentToken, setEnrollmentToken] = useState<string | null>(null)
  const [enrollmentUsername, setEnrollmentUsername] = useState<string | null>(null)

  // Whichever token is "active" right now drives every API call — the full
  // session token once logged in, or the narrow enrollment token during
  // the enroll/verify steps, in that priority order.
  useEffect(() => {
    setAuthToken(session?.token ?? enrollmentToken ?? null)
  }, [session, enrollmentToken])

  // A ref, not a dependency on `session`, so this registers once — reading
  // sessionRef.current inside the handler always sees the latest session
  // without re-subscribing on every login/logout.
  const sessionRef = useRef(session)
  useEffect(() => {
    sessionRef.current = session
  }, [session])

  useEffect(() => {
    // Only a *full* session gets force-cleared on a 401 — a wrong TOTP code
    // during MFA enrollment also 401s, but that's a user retry, not an
    // expired session, and clearing enrollmentToken there would boot the
    // user out of the enrollment flow over a simple typo.
    setUnauthorizedHandler(() => {
      if (sessionRef.current) {
        setSession(null)
        sessionStorage.removeItem(STORAGE_KEY)
      }
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  async function login(username: string, password: string, totpCode?: string) {
    const response = await api.login(username, password, totpCode)
    if (response.mfa_enrollment_required) {
      setEnrollmentToken(response.token)
      setEnrollmentUsername(username)
      return { mfaEnrollmentRequired: true }
    }
    const newSession: Session = {
      token: response.token,
      role: response.role as UserRole,
      username,
      userId: response.user_id,
    }
    setSession(newSession)
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(newSession))
    return { mfaEnrollmentRequired: false }
  }

  function completeMfaEnrollment(): void {
    // The enrollment token never becomes a full session — the user must
    // log in again, this time supplying a valid TOTP code, per auth.py.
    setEnrollmentToken(null)
    setEnrollmentUsername(null)
  }

  async function logout(): Promise<void> {
    try {
      await api.logout()
    } finally {
      setSession(null)
      sessionStorage.removeItem(STORAGE_KEY)
    }
  }

  return (
    <AuthContext.Provider
      value={{ session, enrollmentToken, enrollmentUsername, login, completeMfaEnrollment, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
