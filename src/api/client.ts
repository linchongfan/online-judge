import type { TokenResponse } from '../types'
import { clearAccessToken, getAccessToken, setAccessToken } from './token'

export const API_BASE_URL = '/api/v1'
const DEFAULT_TIMEOUT_MS = 15_000

export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | QueryValue[]>
export type ApiBody = FormData | URLSearchParams | Blob | ArrayBuffer | string

export interface ApiRequestOptions extends Omit<RequestInit, 'body' | 'credentials'> {
  body?: ApiBody | null
  json?: unknown
  query?: QueryParams
  timeoutMs?: number
  skipAuthRefresh?: boolean
  csrf?: boolean
}

interface ErrorPayload {
  code: string
  message: string
  details?: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(
    code: string,
    message: string,
    status = 0,
    details: unknown = null,
    requestId: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
    this.requestId = requestId
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  const entry = document.cookie.split('; ').find((item) => item.startsWith(prefix))
  if (!entry) return null
  try {
    return decodeURIComponent(entry.slice(prefix.length))
  } catch {
    return entry.slice(prefix.length)
  }
}

export function getCsrfToken(): string | null {
  return readCookie('oj_csrf')
}

function buildUrl(path: string, query?: QueryParams): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const url = new URL(`${API_BASE_URL}${normalizedPath}`, window.location.origin)
  if (query) {
    for (const [key, rawValue] of Object.entries(query)) {
      const values = Array.isArray(rawValue) ? rawValue : [rawValue]
      for (const value of values) {
        if (value !== null && value !== undefined) url.searchParams.append(key, String(value))
      }
    }
  }
  return `${url.pathname}${url.search}`
}

async function parseResponse(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new ApiError(
      'INVALID_RESPONSE',
      '服务器返回了无法解析的响应',
      response.status,
      null,
      response.headers.get('X-Request-ID'),
    )
  }
}

function responseError(response: Response, payload: unknown): ApiError {
  const requestId = isRecord(payload) && typeof payload.requestId === 'string'
    ? payload.requestId
    : response.headers.get('X-Request-ID')
  const error = isRecord(payload) && isRecord(payload.error) ? payload.error : null
  const code = error && typeof error.code === 'string' ? error.code : `HTTP_${response.status}`
  const message = error && typeof error.message === 'string' ? error.message : `请求失败（${response.status}）`
  return new ApiError(code, message, response.status, error?.details ?? null, requestId)
}

interface PreparedRequest {
  url: string
  init: RequestInit
  timeoutMs: number
}

function prepareRequest(path: string, options: ApiRequestOptions): PreparedRequest {
  const headers = new Headers(options.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')

  const token = getAccessToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
  if (options.csrf && !headers.has('X-CSRF-Token')) {
    const csrf = getCsrfToken()
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }

  let body: BodyInit | null | undefined = options.body
  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(options.json)
  } else if (options.body instanceof URLSearchParams && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/x-www-form-urlencoded;charset=UTF-8')
  }

  const { json: _json, query, timeoutMs = DEFAULT_TIMEOUT_MS, skipAuthRefresh: _skip, csrf: _csrf, ...init } = options
  return {
    url: buildUrl(path, query),
    init: { ...init, headers, body, credentials: 'include' },
    timeoutMs,
  }
}

async function executeFetch(prepared: PreparedRequest, externalSignal?: AbortSignal | null): Promise<Response> {
  const controller = new AbortController()
  let timedOut = false
  const abortFromOutside = () => controller.abort(externalSignal?.reason)
  if (externalSignal?.aborted) abortFromOutside()
  else externalSignal?.addEventListener('abort', abortFromOutside, { once: true })

  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, prepared.timeoutMs)

  try {
    return await fetch(prepared.url, { ...prepared.init, signal: controller.signal })
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (controller.signal.aborted) {
      if (timedOut) throw new ApiError('TIMEOUT', '请求超时，请稍后重试', 408)
      throw new ApiError('ABORTED', '请求已取消')
    }
    throw new ApiError('NETWORK_ERROR', '无法连接服务器，请检查网络后重试', 0, error)
  } finally {
    window.clearTimeout(timer)
    externalSignal?.removeEventListener('abort', abortFromOutside)
  }
}

async function performRefresh(): Promise<TokenResponse> {
  const headers = new Headers({ Accept: 'application/json' })
  const csrf = getCsrfToken()
  if (csrf) headers.set('X-CSRF-Token', csrf)

  try {
    const response = await executeFetch({
      url: buildUrl('/auth/refresh'),
      init: { method: 'POST', headers, credentials: 'include' },
      timeoutMs: DEFAULT_TIMEOUT_MS,
    })
    const payload = await parseResponse(response)
    if (!response.ok) throw responseError(response, payload)
    const tokenResponse = payload as TokenResponse
    setAccessToken(tokenResponse.accessToken)
    return tokenResponse
  } catch (error) {
    clearAccessToken()
    throw error
  }
}

let refreshPromise: Promise<TokenResponse> | null = null

export type AuthFailureHandler = (error: ApiError) => void

let authFailureHandler: AuthFailureHandler | null = null

/**
 * Called when the refresh credential is rejected for good (401/403). The
 * session store registers a handler that clears in-memory login state so the
 * router guard can send the user back to the login page.
 */
export function onAuthFailure(handler: AuthFailureHandler | null): void {
  authFailureHandler = handler
}

export function refreshAccessToken(): Promise<TokenResponse> {
  if (!refreshPromise) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

export async function request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const prepared = prepareRequest(path, options)
  const response = await executeFetch(prepared, options.signal)
  const payload = await parseResponse(response)

  if (response.ok) return payload as T
  const originalError = responseError(response, payload)
  if (response.status !== 401 || options.skipAuthRefresh) throw originalError

  try {
    await refreshAccessToken()
  } catch (error) {
    // Only a rejected credential invalidates the session; transient network
    // failures must keep the user logged in.
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      authFailureHandler?.(error)
    }
    // Callers decide whether authentication is required. Public requests never redirect.
    throw originalError
  }

  const retry = prepareRequest(path, options)
  const retryResponse = await executeFetch(retry, options.signal)
  const retryPayload = await parseResponse(retryResponse)
  if (!retryResponse.ok) throw responseError(retryResponse, retryPayload)
  return retryPayload as T
}

export const apiRequest = request
