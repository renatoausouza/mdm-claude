import { useState } from 'react'
import { useLanguage } from '../i18n/LanguageContext'

// Shared by ReviewDetailPage and DuplicateResolvePage: both submit a
// decision (approve/reject/request-info, or accept/reject a duplicate) and
// need the same busy/error/success-message dance around it, then reload the
// underlying record so its new status is reflected immediately.
export function useReviewAction() {
  const { t } = useLanguage()
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function run(
    action: () => Promise<{ status: string }>,
    // 'common.job' or 'common.case' — a translation key, not display text,
    // so the eventual message is built in whatever language is active when
    // the response actually comes back (not when `run` was called).
    subjectKey: 'common.job' | 'common.case',
    onSuccess: () => void,
  ): Promise<void> {
    setActionError(null)
    setBusy(true)
    try {
      const response = await action()
      setMessage(t('common.statusUpdateMessage', { subject: t(subjectKey), status: t(`status.${response.status}`) }))
      onSuccess()
    } catch (err) {
      setActionError(err)
    } finally {
      setBusy(false)
    }
  }

  return { busy, setBusy, actionError, setActionError, message, run }
}
