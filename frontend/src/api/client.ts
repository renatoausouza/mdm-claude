// Thin fetch wrapper: JSON in/out, Bearer auth, typed errors. Endpoint
// functions for each backend route live in api/endpoints.ts and call
// `request`/`upload` here rather than using fetch directly.

let authToken: string | null = null

export function setAuthToken(token: string | null): void {
  authToken = token
}

export function getAuthToken(): string | null {
  return authToken
}

// AuthContext registers a handler here so a 401 from any request (session
// expired, token revoked server-side) can clear the stale session — without
// this, a page whose fetch starts failing with 401 just shows a per-page
// error banner forever while Layout keeps rendering the logged-in chrome.
let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed with status ${status}`)
    this.status = status
    this.detail = detail
  }
}

async function parseErrorDetail(response: Response): Promise<unknown> {
  try {
    const body = await response.json()
    // FastAPI's default error shape is {"detail": "..."} or
    // {"detail": [{"msg": "...", ...}, ...]} for Pydantic validation errors.
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail)) {
        return detail
          .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
          .join('; ')
      }
      return detail
    }
    return body
  } catch {
    return response.statusText
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  params?: Record<string, string | undefined>
}

function buildUrl(path: string, params?: Record<string, string | undefined>): string {
  if (!params) return path
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, value)
  }
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(buildUrl(path, options.params), {
    method: options.method ?? (options.body !== undefined ? 'POST' : 'GET'),
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.()
    throw new ApiError(response.status, await parseErrorDetail(response))
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function uploadFile<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {}
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`

  const response = await fetch(path, { method: 'POST', headers, body: formData })
  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.()
    throw new ApiError(response.status, await parseErrorDetail(response))
  }
  return (await response.json()) as T
}
