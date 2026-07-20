import type { Domain } from '../types/api'

const MONOGRAM: Record<Domain, string> = { supplier: 'S', client: 'C', product: 'P' }

export function DomainMark({ domain }: { domain: Domain }) {
  return (
    <span className="domain-mark" aria-hidden="true">
      {MONOGRAM[domain]}
    </span>
  )
}
