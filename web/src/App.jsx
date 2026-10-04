import { Component, useState } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { setCredentials, logout } from './app/authSlice'
import { useLoginMutation } from './app/api'
import ApplyDashboard from './pages/ApplyDashboard'
import AnalystDashboard from './pages/AnalystDashboard'
import { Button } from './components/ui'

const SURFACES = [
  { key: 'apply', label: 'Application' },
  { key: 'analyst', label: 'Analyst' },
]

function SignIn({ onSignedIn }) {
  const dispatch = useDispatch()
  const [username, setUsername] = useState('analyst')
  const [password, setPassword] = useState('')
  const [login, { isLoading }] = useLoginMutation()
  const [error, setError] = useState(null)

  async function submit(event) {
    event.preventDefault()
    setError(null)
    try {
      const res = await login({ username, password }).unwrap()
      dispatch(setCredentials(res))
      onSignedIn()
    } catch (err) {
      if (err?.status === 401) {
        // Deliberately uniform error text -- backend gives no signal about
        // which field was wrong (see AuthController.java).
        setError('Those details did not match an account.')
      } else {
        // Network failure (FETCH_ERROR), timeout, 5xx: not the user's fault.
        setError('The service is unavailable right now. Please try again in a moment.')
      }
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm">
        <h1 className="text-[20px] font-semibold tracking-tight">VIGIL</h1>
        <p className="mt-0.5 text-[13px] text-ink-muted">
          Real-time fraud decisioning for Indian digital lending.
        </p>

        <div className="mt-6 space-y-3">
          <label className="block">
            <span className="text-[12px] text-ink-muted">Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              className="mt-1 w-full border border-rule bg-surface px-2.5 py-2 text-[14px]"
            />
          </label>
          <label className="block">
            <span className="text-[12px] text-ink-muted">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="mt-1 w-full border border-rule bg-surface px-2.5 py-2 text-[14px]"
            />
          </label>
        </div>

        {error && <p className="mt-3 text-[13px] text-[#9c3211]">{error}</p>}

        <Button variant="primary" className="mt-4 w-full" disabled={isLoading}>
          {isLoading ? 'Signing in…' : 'Sign in'}
        </Button>

        <p className="mt-6 border-t border-rule-soft pt-3 text-[11px] leading-relaxed text-ink-faint">
          Demo accounts: <span className="hash">analyst</span> / <span className="hash">admin</span>.
          Retraining the model requires the admin role.
        </p>
      </form>
    </div>
  )
}

/** Keeps one bad payload from blanking the whole app; resets when `resetKey` changes. */
class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidUpdate(prev) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="mx-auto max-w-xl p-8 text-center">
        <p className="text-[14px] font-medium text-[#9c3211]">This view hit an unexpected error.</p>
        <p className="mt-1 text-[12px] text-ink-muted">{String(this.state.error?.message || this.state.error)}</p>
        <Button className="mt-4" onClick={() => this.setState({ error: null })}>Try again</Button>
      </div>
    )
  }
}

export default function App() {
  const { token, displayName, role } = useSelector((s) => s.auth)
  const dispatch = useDispatch()
  const [surface, setSurface] = useState('apply')

  if (!token) {
    return <SignIn onSignedIn={() => {}} />
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-6 border-b border-rule bg-surface px-5 py-2.5">
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-tight">VIGIL</span>
          <span className="hidden text-[12px] text-ink-faint sm:inline">
            fraud decisioning
          </span>
        </div>

        <nav className="flex gap-1">
          {SURFACES.map((item) => (
            <button
              key={item.key}
              onClick={() => setSurface(item.key)}
              aria-current={surface === item.key}
              className={`rounded-sm px-2.5 py-1 text-[13px] transition-colors ${
                surface === item.key
                  ? 'bg-paper font-medium text-ink'
                  : 'text-ink-muted hover:text-ink'
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-[12px] text-ink-faint">{displayName} · {role}</span>
          <Button onClick={() => dispatch(logout())}>Sign out</Button>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto bg-paper">
        <ErrorBoundary resetKey={surface}>
          {surface === 'apply' && <ApplyDashboard />}
          {surface === 'analyst' && <AnalystDashboard />}
        </ErrorBoundary>
      </main>
    </div>
  )
}
