import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { DOMAIN_LABELS, DOMAINS } from '../types/api'
import { DomainMark } from './DomainMark'

export function Layout() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="app-shell">
      <aside className="app-rail">
        <div className="app-brand">
          <span className="app-seal" aria-hidden="true">
            M
          </span>
          <span className="app-brand-text">
            MDM
            <span className="app-brand-caption">Master Data Registry</span>
          </span>
        </div>

        <nav className="app-nav">
          <NavLink to="/upload" className="app-nav-link">
            Intake
          </NavLink>

          <div className="app-nav-section">Queues</div>
          {DOMAINS.map((domain) => (
            <NavLink key={domain} to={`/queue/${domain}`} className="app-nav-link app-nav-link-domain">
              <DomainMark domain={domain} />
              {DOMAIN_LABELS[domain]}
            </NavLink>
          ))}

          {session?.role === 'admin' && (
            <>
              <div className="app-nav-section">Records</div>
              <NavLink to="/audit-log" className="app-nav-link">
                Audit log
              </NavLink>
            </>
          )}
        </nav>

        {session && (
          <div className="app-user">
            <div className="app-username">{session.username}</div>
            <div className="app-role">{session.role}</div>
            <button type="button" onClick={handleLogout} className="app-logout">
              Log out
            </button>
          </div>
        )}
      </aside>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  )
}
