import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useLanguage } from '../i18n/LanguageContext'
import { DOMAINS } from '../types/api'

export function HomePage() {
  const { session } = useAuth()
  const { t } = useLanguage()

  return (
    <div>
      <h1>
        {t('home.welcome')}
        {session ? `, ${session.username}` : ''}
      </h1>
      <p>{t('home.intro')}</p>
      <div className="home-links">
        <Link to="/upload">{t('home.uploadLink')}</Link>
        {DOMAINS.map((domain) => (
          <Link key={domain} to={`/queue/${domain}`}>
            {t('home.queueLink', { domain: t(`domain.${domain}`) })}
          </Link>
        ))}
        <Link to="/help">{t('home.helpLink')}</Link>
        {session?.role === 'admin' && <Link to="/audit-log">{t('layout.navAuditLog')}</Link>}
      </div>
    </div>
  )
}
