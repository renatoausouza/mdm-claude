import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { UserRole } from '../types/api'

interface ProtectedRouteProps {
  children: ReactNode
  // When set, only these roles may view the route — anyone else is
  // redirected home rather than shown a 403 (mirrors the backend rejecting
  // the action; this just avoids rendering UI for actions that would fail).
  allowedRoles?: UserRole[]
}

export function ProtectedRoute({ children, allowedRoles }: ProtectedRouteProps) {
  const { session } = useAuth()
  const location = useLocation()

  if (!session) {
    // LoginPage reads location.state.from to send the user back to the
    // page they actually asked for (e.g. a shared deep link), instead of
    // always landing on Home after signing in.
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  if (allowedRoles && !allowedRoles.includes(session.role)) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}
