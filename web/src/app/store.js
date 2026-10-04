import { configureStore } from '@reduxjs/toolkit'
import { api } from './api'
import authReducer from './authSlice'

export const store = configureStore({
  reducer: {
    auth: authReducer,
    [api.reducerPath]: api.reducer,
  },
  middleware: (getDefault) => getDefault().concat(api.middleware),
})

// Persist the session outside the reducer, and drop every cached response the
// moment the token goes away so the next user never sees the previous one's data.
let lastAuth = store.getState().auth
store.subscribe(() => {
  const auth = store.getState().auth
  if (auth === lastAuth) return
  const hadToken = !!lastAuth.token
  lastAuth = auth
  try {
    if (auth.token) localStorage.setItem('vigil_auth', JSON.stringify(auth))
    else localStorage.removeItem('vigil_auth')
  } catch {
    // ignore storage failures (private window etc.) -- session still works in memory
  }
  if (hadToken && !auth.token) store.dispatch(api.util.resetApiState())
})
