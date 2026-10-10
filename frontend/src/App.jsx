import { useEffect, useState } from 'react';
import { ArrowRight, CheckCircle2, LayoutDashboard, LoaderCircle, LockKeyhole, LogOut, RefreshCw, ShieldCheck, UserRound, Waves } from 'lucide-react';
import Login from './components/shared/Login';
import { api, clearSession, readSession, saveSession, SESSION_EXPIRED_EVENT } from './services/api';

const workspaces = [
  { role: 'citizen', label: 'Citizen', path: '/api/workspaces/citizen' },
  { role: 'admin', label: 'Admin', path: '/api/workspaces/admin' },
  { role: 'response_team', label: 'Response team', path: '/api/workspaces/response-team' },
];
const roleLabel = role => workspaces.find(item => item.role === role)?.label || role;

function PermissionsWorkspace({ user }) {
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setResults([]);
    Promise.all(workspaces.map(async workspace => {
      try {
        const payload = await api(workspace.path, { signal: controller.signal });
        return { ...workspace, status: 200, payload };
      } catch (error) {
        if (error.name === 'AbortError') throw error;
        return { ...workspace, status: error.status, error: error.message };
      }
    }))
      .then(value => { if (!controller.signal.aborted) setResults(value); })
      .catch(() => {})
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [user.id, user.role, attempt]);

  const current = results.find(item => item.role === user.role);
  return (
    <>
      <div className="page-heading">
        <div><span className="eyebrow">ATHUL · WEEK 1</span><h1>{roleLabel(user.role)} workspace</h1><p>Authentication and role access, verified through the backend.</p></div>
        <button className="button secondary" onClick={() => setAttempt(value => value + 1)} disabled={busy}><RefreshCw size={16} className={busy ? 'spin' : ''} />Check access again</button>
      </div>
      <section className="workspace-hero" aria-label="Your role access">
        <span className="hero-icon"><ShieldCheck size={32} /></span>
        <div>
          <span className="eyebrow">YOUR SIGNED-IN ROLE</span>
          <h2>{busy ? 'Checking workspace permissions…' : current?.payload?.title || 'Workspace access needs attention'}</h2>
          <p>{busy ? 'The server is checking access to each role workspace using your session.' : current?.payload?.message || current?.error || 'Your current role could not be verified.'}</p>
          {!busy && current?.status === 200 && <span className="access-badge"><CheckCircle2 size={15} />Server accepted your {roleLabel(user.role).toLowerCase()} session</span>}
        </div>
      </section>
      <section className="panel" aria-labelledby="permissions-heading">
        <div className="panel-heading"><div><h2 id="permissions-heading">Workspace permissions</h2><p>Actual results of requests to the protected pages.</p></div><span className="outline-tag">SERVER CHECKED</span></div>
        <div className="table-wrap"><table className="permissions-table">
          <thead><tr><th scope="col">Workspace</th><th scope="col">Your access</th><th scope="col">Server response</th></tr></thead>
          <tbody>{workspaces.map(workspace => {
            const result = results.find(item => item.role === workspace.role);
            const allowed = result?.status === 200;
            const denied = result?.status === 403;
            return <tr key={workspace.role}><th scope="row">{workspace.label}</th><td><span className={`permission-state ${allowed ? 'allowed' : denied ? 'denied' : ''}`}>{busy ? <LoaderCircle size={14} className="spin" /> : allowed ? <CheckCircle2 size={14} /> : denied ? <LockKeyhole size={14} /> : null}{busy ? 'Checking' : allowed ? 'Allowed' : denied ? 'Denied by server' : 'Check failed'}</span></td><td>{busy ? 'Waiting…' : result?.status ? `HTTP ${result.status}` : 'Server unavailable'}</td></tr>;
          })}</tbody>
        </table></div>
        {!busy && results.some(result => result.status !== 200 && result.status !== 403) && <p className="error-box panel-error" role="alert">One or more permission checks could not complete. Check the server and try again.</p>}
        <p className="panel-note">Only your permitted workspace and account page appear in navigation. These pages demonstrate role access for Athul's Week 1 scope.</p>
      </section>
    </>
  );
}

function Account({ user }) {
  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">ACCOUNT DETAILS</span><h1>My account</h1><p>Your profile comes from the authenticated backend session.</p></div></div>
      <section className="panel account-panel" aria-labelledby="account-heading">
        <div className="panel-heading"><div><h2 id="account-heading">Signed-in profile</h2><p>The server owns your identity and role.</p></div><UserRound size={23} /></div>
        <dl className="account-facts">
          <div><dt>Full name</dt><dd>{user.full_name}</dd></div>
          <div><dt>Email address</dt><dd>{user.email}</dd></div>
          <div><dt>Role</dt><dd>{roleLabel(user.role)}</dd></div>
          <div><dt>User ID</dt><dd>{user.id}</dd></div>
          {user.team_id && <div><dt>Team ID</dt><dd>{user.team_id}</dd></div>}
        </dl>
        <p className="panel-note">Public registration creates citizen accounts. Admin and response team roles are provisioned by the local administrator.</p>
      </section>
    </>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(Boolean(readSession()));
  const [bootError, setBootError] = useState('');
  const [bootAttempt, setBootAttempt] = useState(0);
  const [view, setView] = useState('workspace');
  const [notice, setNotice] = useState('');
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    function expireSession() {
      clearSession();
      setUser(null);
      setNotice('Your session has expired. Please sign in again.');
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, expireSession);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expireSession);
  }, []);

  useEffect(() => {
    if (!readSession()) { setBooting(false); return undefined; }
    const controller = new AbortController();
    setBooting(true);
    setBootError('');
    api('/api/users/me', { signal: controller.signal })
      .then(profile => { saveSession({ ...readSession(), user: profile }); setUser(profile); setView('workspace'); })
      .catch(error => {
        if (error.name === 'AbortError') return;
        if (error.status === 401 || error.status === 403) {
          clearSession(); setNotice('Your session has expired. Please sign in again.');
        } else setBootError(error.message);
      })
      .finally(() => { if (!controller.signal.aborted) setBooting(false); });
    return () => controller.abort();
  }, [bootAttempt]);

  async function login(session) {
    saveSession(session);
    try {
      const profile = await api('/api/users/me');
      saveSession({ ...session, user: profile });
      setUser(profile);
      setView('workspace');
      setNotice('');
    } catch (error) {
      clearSession();
      throw error;
    }
  }

  async function logout() {
    setLoggingOut(true);
    let message = 'You have signed out. Your server session has been revoked.';
    try { await api('/api/auth/logout', { method: 'POST' }); }
    catch (error) { message = `You have signed out on this device. The server could not confirm session revocation: ${error.message}`; }
    finally { clearSession(); setUser(null); setNotice(message); setLoggingOut(false); }
  }

  function navigate(next) {
    setView(next);
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  if (booting) return <main className="startup-state"><span className="brand-symbol"><Waves /></span><LoaderCircle className="spin" size={24} /><p>Verifying your session…</p></main>;
  if (bootError) return <main className="startup-state"><span className="brand-symbol"><Waves /></span><h1>Reconnect your workspace.</h1><p className="error-box" role="alert">{bootError}</p><div className="button-row"><button className="button primary" onClick={() => setBootAttempt(value => value + 1)}>Try again<ArrowRight size={17} /></button><button className="button secondary" onClick={() => { clearSession(); setBootError(''); }}>Sign in again</button></div></main>;
  if (!user) return <Login onLogin={login} notice={notice} />;

  const initials = user.full_name.split(' ').filter(Boolean).map(part => part[0]).slice(0, 2).join('').toUpperCase();
  const links = [{ id: 'workspace', label: `${roleLabel(user.role)} workspace`, icon: LayoutDashboard }, { id: 'account', label: 'My account', icon: UserRound }];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar">
        <a className="brand" href="#" onClick={event => { event.preventDefault(); navigate('workspace'); }}><span className="brand-symbol"><Waves size={25} /></span><span>ResQ <strong>Kerala</strong><small>ATHUL · WEEK 1</small></span></a>
        <div className="workspace-pill"><ShieldCheck size={14} />{roleLabel(user.role)} account</div>
        <div className="navigation-label">YOUR WORKSPACE</div>
        <nav aria-label="Main navigation">{links.map(link => <button type="button" key={link.id} onClick={() => navigate(link.id)} className={view === link.id ? 'nav-link active' : 'nav-link'} aria-current={view === link.id ? 'page' : undefined}><link.icon size={19} /><span>{link.label}</span></button>)}</nav>
        <div className="sidebar-bottom">
          <div className="foundation-card"><span className="eyebrow light">ATHUL · WEEK 1</span><p>Authentication.<br />Role permissions.</p><span>Local demonstration</span></div>
          <div className="profile-block"><span className="avatar">{initials}</span><span className="profile-name"><strong>{user.full_name}</strong><small>{roleLabel(user.role)}</small></span><button className="logout-button" type="button" onClick={logout} disabled={loggingOut} aria-label="Sign out">{loggingOut ? <LoaderCircle size={18} className="spin" /> : <LogOut size={18} />}</button></div>
        </div>
      </aside>
      <div className="workspace">
        <header className="workspace-header"><span>Athul <span className="breadcrumb-divider">/</span> {links.find(link => link.id === view)?.label}</span><span className="week-tag">WEEK 1</span></header>
        <main id="main-content" className="workspace-main">{view === 'account' ? <Account user={user} /> : <PermissionsWorkspace user={user} />}</main>
        <footer className="workspace-footer"><span>ResQ Kerala · Athul</span><span>Authentication and role permissions demo</span></footer>
      </div>
    </div>
  );
}
