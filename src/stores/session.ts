import { reactive } from 'vue'
import {
  changePassword as changePasswordRequest,
  getProfile,
  updateProfile as updateProfileRequest,
} from '../api/me'
import {
  login as loginRequest,
  logout as logoutRequest,
  register as registerRequest,
} from '../api/auth'
import { ApiError, onAuthFailure } from '../api/client'
import { clearAccessToken } from '../api/token'
import type {
  LoginRequest,
  MessageResponse,
  PasswordChangeRequest,
  ProfileUpdateRequest,
  RegisterRequest,
  UserProfile,
  UserRole,
} from '../types'

interface SessionState {
  loggedIn: boolean
  initializing: boolean
  initialized: boolean
  profile: UserProfile | null
  role: UserRole | null
}

export const session = reactive<SessionState>({
  loggedIn: false,
  initializing: true,
  initialized: false,
  profile: null,
  role: null,
})

function applyProfile(profile: UserProfile): UserProfile {
  session.profile = profile
  session.role = profile.role
  session.loggedIn = true
  session.initialized = true
  session.initializing = false
  return profile
}

function clearSession(): void {
  clearAccessToken()
  session.profile = null
  session.role = null
  session.loggedIn = false
  session.initializing = false
}

// A refresh credential rejected for good invalidates the in-memory session;
// the router guard then redirects protected pages to the login screen.
onAuthFailure(() => {
  clearSession()
  session.initialized = true
})

let initialization: Promise<UserProfile | null> | null = null

export function initializeSession(): Promise<UserProfile | null> {
  if (session.initialized) return Promise.resolve(session.profile)
  if (initialization) return initialization

  session.initializing = true
  initialization = getProfile()
    .then((profile) => applyProfile(profile))
    .catch((error: unknown) => {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        clearSession()
        session.initialized = true
        return null
      }
      // Transient failure (network, 5xx): stay uninitialized so the next
      // navigation retries instead of permanently treating the user as guest.
      session.initializing = false
      return null
    })
    .finally(() => {
      initialization = null
    })
  return initialization
}

export async function login(credentials: LoginRequest): Promise<UserProfile> {
  const response = await loginRequest(credentials)
  return applyProfile(response.user)
}

export async function register(credentials: RegisterRequest): Promise<UserProfile> {
  const response = await registerRequest(credentials)
  return applyProfile(response.user)
}

export async function logout(): Promise<MessageResponse | null> {
  try {
    return await logoutRequest()
  } finally {
    clearSession()
    session.initialized = true
  }
}

export async function updateProfile(data: ProfileUpdateRequest): Promise<UserProfile> {
  const profile = await updateProfileRequest(data)
  return applyProfile(profile)
}

export async function changePassword(data: PasswordChangeRequest): Promise<MessageResponse> {
  const response = await changePasswordRequest(data)
  clearSession()
  session.initialized = true
  return response
}
