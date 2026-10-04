import { createSlice } from '@reduxjs/toolkit'

const EMPTY = { token: null, username: null, role: null, displayName: null }

/** Decode the JWT payload (base64url) without verifying -- the server does that. */
function jwtExp(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = decodeURIComponent(
      atob(payload).split('').map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join(''),
    )
    const exp = JSON.parse(json).exp
    return typeof exp === 'number' ? exp : null
  } catch {
    return null
  }
}

/** True if the token carries an exp claim that has passed. Opaque tokens are left to the server. */
export function isTokenExpired(token) {
  const exp = jwtExp(token)
  return exp != null && exp * 1000 <= Date.now()
}

const stored = (() => {
  try {
    const raw = localStorage.getItem('vigil_auth')
    const parsed = raw ? JSON.parse(raw) : null
    if (!parsed?.token || isTokenExpired(parsed.token)) return null
    return { ...EMPTY, ...parsed }
  } catch {
    return null
  }
})()

const authSlice = createSlice({
  name: 'auth',
  initialState: stored || EMPTY,
  // Pure reducers: persistence lives in store.js.
  reducers: {
    setCredentials: (state, action) => {
      const { token, username, role, displayName } = action.payload
      state.token = token
      state.username = username
      state.role = role
      state.displayName = displayName
    },
    logout: () => EMPTY,
  },
})

export const { setCredentials, logout } = authSlice.actions
export default authSlice.reducer
