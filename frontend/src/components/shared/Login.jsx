import { useState } from 'react';
import { ArrowRight, Check, LoaderCircle, ShieldCheck, Waves } from 'lucide-react';
import { api } from '../../services/api';

export default function Login({ onLogin, notice = '' }) {
  const [mode, setMode] = useState('login');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      const credentials = { email: email.trim().toLowerCase(), password };
      const session = mode === 'register'
        ? await api('/api/auth/register', { method: 'POST', body: { ...credentials, full_name: fullName.trim() } })
        : await api('/api/auth/login', { method: 'POST', body: credentials });
      await onLogin(session);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  function changeMode(next) {
    setMode(next);
    setError('');
    setPassword('');
  }

  return (
    <main className="auth-layout">
      <section className="auth-story" aria-label="Athul's Week 1 work">
        <a className="brand auth-brand" href="#" aria-label="ResQ Kerala home">
          <span className="brand-symbol"><Waves size={26} /></span>
          <span>ResQ <strong>Kerala</strong><small>ATHUL · WEEK 1</small></span>
        </a>
        <div className="story-copy">
          <span className="eyebrow light">AUTHENTICATION & ROLE ACCESS</span>
          <h1>The right access.<br />For every account.</h1>
          <p>Athul's first-week foundation: account creation, secure sign-in, sign-out, and access controlled by the server.</p>
          <div className="story-steps">
            {['Create a citizen account', 'Sign in to your role', 'Verify workspace permissions'].map((step, index) => (
              <div key={step}><span>{String(index + 1).padStart(2, '0')}</span>{step}<Check size={15} /></div>
            ))}
          </div>
        </div>
        <svg className="contour-art" viewBox="0 0 600 400" aria-hidden="true">
          {[0, 1, 2, 3, 4, 5, 6, 7].map(index => <path key={index} d={`M -50 ${140 + index * 28} C 90 ${-30 + index * 33}, 240 ${370 + index * 12}, 650 ${100 + index * 37}`} />)}
        </svg>
        <p className="story-footer">ResQ Kerala · Member-specific foundation</p>
      </section>
      <section className="auth-main">
        <div className="auth-topline"><ShieldCheck size={17} /><span>Authentication and role permissions</span></div>
        <div className="auth-card">
          <span className="eyebrow">ATHUL · WEEK 1</span>
          <h2>{mode === 'login' ? 'Welcome to your workspace.' : 'Create your account.'}</h2>
          <p className="auth-intro">{mode === 'login' ? 'Sign in to verify your account and open the workspace allowed for your role.' : 'Register as a citizen. Your permissions are assigned by the server.'}</p>
          <div className="auth-tabs" aria-label="Account access">
            <button type="button" className={mode === 'login' ? 'active' : ''} aria-pressed={mode === 'login'} onClick={() => changeMode('login')} disabled={busy}>Sign in</button>
            <button type="button" className={mode === 'register' ? 'active' : ''} aria-pressed={mode === 'register'} onClick={() => changeMode('register')} disabled={busy}>Create account</button>
          </div>
          {notice && <p className="notice" role="status">{notice}</p>}
          <form onSubmit={submit} className="auth-form">
            {mode === 'register' && <label>Full name<input type="text" value={fullName} onChange={event => setFullName(event.target.value)} autoComplete="name" required minLength={3} maxLength={100} placeholder="How should we address you?" disabled={busy} /></label>}
            <label>Email address<input type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="username" required maxLength={254} placeholder="you@example.com" disabled={busy} /></label>
            <label>Password<input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} required minLength={mode === 'register' ? 10 : undefined} maxLength={128} placeholder={mode === 'register' ? 'At least 10 characters' : 'Enter your password'} disabled={busy} /></label>
            {error && <p className="error-box" role="alert">{error}</p>}
            <button className="button primary auth-submit" type="submit" disabled={busy}>{busy ? <><LoaderCircle className="spin" size={18} />{mode === 'register' ? 'Creating your account…' : 'Signing in…'}</> : <>{mode === 'register' ? 'Create citizen account' : 'Sign in'}<ArrowRight size={18} /></>}</button>
          </form>
          <p className="auth-help">{mode === 'register' ? 'Admin and response team accounts are created by the local setup script.' : 'Demo credentials are generated locally. See Athul/README.md and Athul/.runtime/demo-accounts.json.'}</p>
        </div>
        <div className="prototype-note"><span className="outline-tag">WEEK 1 AUTH DEMO</span> Athul's authentication and permissions tasks</div>
      </section>
    </main>
  );
}
