import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useLanguage } from '../i18n/LanguageContext'
import { DOMAINS } from '../types/api'
import { DomainMark } from './DomainMark'
import { LanguageToggle } from './LanguageToggle'

export function Layout() {
  const { session, logout } = useAuth()
  const { t } = useLanguage()
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
            <span className="app-brand-caption">{t('layout.brandCaption')}</span>
          </span>
        </div>

        <nav className="app-nav">
          <NavLink to="/upload" className="app-nav-link">
            {t('layout.navIntake')}
          </NavLink>

          <div className="app-nav-section">{t('layout.navQueuesSection')}</div>
          {DOMAINS.map((domain) => (
            <NavLink key={domain} to={`/queue/${domain}`} className="app-nav-link app-nav-link-domain">
              <DomainMark domain={domain} />
              {t(`domain.${domain}`)}
            </NavLink>
          ))}

          {(session?.role === 'approver' || session?.role === 'admin') && (
            <>
              <div className="app-nav-section">{t('layout.navMasterDataSection')}</div>
              {DOMAINS.map((domain) => (
                <NavLink
                  key={domain}
                  to={`/master-data/${domain}`}
                  className="app-nav-link app-nav-link-domain"
                >
                  <DomainMark domain={domain} />
                  {t(`domain.${domain}`)}
                </NavLink>
              ))}
            </>
          )}

          <div className="app-nav-section">{t('layout.navRecordsSection')}</div>
          <NavLink to="/help" className="app-nav-link">
            {t('layout.navHelp')}
          </NavLink>
          {session?.role === 'admin' && (
            <NavLink to="/audit-log" className="app-nav-link">
              {t('layout.navAuditLog')}
            </NavLink>
          )}
        </nav>

        <LanguageToggle className="app-language-toggle" />

        {session && (
          <div className="app-user">
            <div className="app-username">{session.username}</div>
            <div className="app-role">{t(`role.${session.role}`)}</div>
            <button type="button" onClick={handleLogout} className="app-logout">
              {t('layout.logout')}
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
