import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAgentName } from "../hooks/useAgentName";
import { setStaffToken } from "../hooks/useStaffSession";
import { api } from "../services/api";
import { Logo } from "../site/Logo";

/** Sign-in for support agents and reviewers. Customers use the help center and chat without an account. */
export function LoginPage() {
  const [, setAgentName] = useAgentName();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await api.login(username.trim(), password);
      setAgentName(session.user.display_name);
      setStaffToken(session.token);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <main className="login-shell">
      <form className="card login-card stack" onSubmit={submit} aria-labelledby="login-title">
        <div className="brand" style={{ padding: 0 }}>
          <Logo size={34} />
          <span><span className="brand-name">Support IQ</span><br /><span className="brand-sub">Agent workspace</span></span>
        </div>
        <h1 id="login-title" className="login-title">Sign in</h1>
        <div className="field">
          <label htmlFor="login-username">Username</label>
          <input id="login-username" className="input" autoComplete="username" value={username} maxLength={80} required autoFocus
            onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="login-password">Password</label>
          <input id="login-password" className="input" type="password" autoComplete="current-password" value={password}
            maxLength={200} required onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={busy || !username.trim() || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="muted small" style={{ margin: 0 }}>Looking for help with your own service? <Link to="/">Go to the help center</Link>.</p>
      </form>
    </main>
  );
}
