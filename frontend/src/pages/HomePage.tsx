import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { DOMAIN_LABELS, DOMAINS } from '../types/api'

export function HomePage() {
  const { session } = useAuth()

  return (
    <div>
      <h1>Welcome{session ? `, ${session.username}` : ''}</h1>
      <p>Master data registration — upload a document, then review candidates in the queues below.</p>
      <div className="home-links">
        <Link to="/upload">Upload a document</Link>
        {DOMAINS.map((domain) => (
          <Link key={domain} to={`/queue/${domain}`}>
            {DOMAIN_LABELS[domain]} review queue
          </Link>
        ))}
        {session?.role === 'admin' && <Link to="/audit-log">Audit log</Link>}
      </div>
    </div>
  )
}
