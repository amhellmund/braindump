import { useState, useCallback } from 'react'
import logo from '../assets/logo.png'
import { useAuth } from '../auth'
import { fetchLogin } from '../api'
import './LoginPage.css'

interface Props {
  onLogin: () => void
}

export default function LoginPage({ onLogin }: Props) {
  const { setAuth } = useAuth()
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token.trim()) {
      setError('Please enter your access token.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await fetchLogin(token.trim())
      setAuth(data.username)
      onLogin()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not reach the server.')
    } finally {
      setLoading(false)
    }
  }, [token, setAuth, onLogin])

  return (
    <div className="login-page">
      <div className="login-card">
        <img src={logo} alt="braindump" className="login-logo" />
        <form className="login-form" onSubmit={handleSubmit}>
          <label className="login-label" htmlFor="login-token">Access token</label>
          <input
            id="login-token"
            className="login-input"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setToken(e.target.value)}
            placeholder="bd_…"
            disabled={loading}
          />
          {error && <p className="login-error">{error}</p>}
          <button className="login-btn" type="submit" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
