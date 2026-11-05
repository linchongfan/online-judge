let accessToken: string | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token || null
}

export function clearAccessToken(): void {
  accessToken = null
}
