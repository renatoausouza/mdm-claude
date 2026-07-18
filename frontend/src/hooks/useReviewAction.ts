import { useState } from 'react'
import { humanize } from '../utils'

// Shared by ReviewDetailPage and DuplicateResolvePage: both submit a
// decision (approve/reject/request-info, or accept/reject a duplicate) and
// need the same busy/error/success-message dance around it, then reload the
// underlying record so its new status is reflected immediately.
export function useReviewAction() {
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function run(
    action: () => Promise<{ status: string }>,
    subject: string,
    onSuccess: () => void,
  ): Promise<void> {
    setActionError(null)
    setBusy(true)
    try {
      const response = await action()
      setMessage(`${subject} is now ${humanize(response.status)}.`)
      onSuccess()
    } catch (err) {
      setActionError(err)
    } finally {
      setBusy(false)
    }
  }

  return { busy, setBusy, actionError, setActionError, message, run }
}
