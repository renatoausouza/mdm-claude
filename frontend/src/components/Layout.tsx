import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { DOMAIN_LABELS, DOMAINS } from '../types/api'

export function Layout() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">MDM</div>
        <nav className="app-nav">
          <NavLink to="/upload">Upload</NavLink>
          {DOMAINS.map((domain) => (
            <NavLink key={domain} to={`/queue/${domain}`}>
              {DOMAIN_LABELS[domain]} queue
            </NavLink>
          ))}
          {session?.role === 'admin' && <NavLink to="/audit-log">Audit log</NavLink>}
        </nav>
        <div className="app-user">
          {session && (
            <>
              <span className="app-username">
                {session.username} <span className="app-role">({session.role})</span>
              </span>
              <button type="button" onClick={handleLogout}>
                Log out
              </button>
            </>
          )}
        </div>
      </header>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  )
}
