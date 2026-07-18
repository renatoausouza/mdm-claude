import { humanize } from '../utils'

const STATUS_CLASS: Record<string, string> = {
  pending_review: 'status-pending',
  needs_info: 'status-pending',
  approved: 'status-approved',
  accepted: 'status-approved',
  partially_accepted: 'status-approved',
  rejected: 'status-rejected',
  extraction_failed: 'status-rejected',
  unsupported_format: 'status-rejected',
  queued: 'status-neutral',
  pending: 'status-pending',
}

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_CLASS[status] ?? 'status-neutral'
  return <span className={`status-badge ${cls}`}>{humanize(status)}</span>
}
