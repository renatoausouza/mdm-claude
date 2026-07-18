import { ApiError } from '../api/client'

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail)
  }
  if (error instanceof Error) return error.message
  return String(error)
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null
  return <div className="error-banner">{errorMessage(error)}</div>
}
