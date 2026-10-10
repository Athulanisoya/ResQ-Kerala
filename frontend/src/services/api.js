export const SESSION_KEY = 'athul-week1-session';
export const SESSION_EXPIRED_EVENT = 'athul:session-expired';

export function readSession() {
  try {
    const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
    return value?.access_token && value?.user ? value : null;
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function saveSession(session) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

export async function api(path, { method = 'GET', body, signal } = {}) {
  const token = readSession()?.access_token;
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Unable to reach the server. Check that the backend is running, then try again.');
  }
  const result = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    let message = 'The request could not be completed. Please try again.';
    if (typeof result?.detail === 'string') message = result.detail;
    else if (Array.isArray(result?.detail)) {
      message = result.detail.map(item => `${item.loc?.slice(1).join(' ') || 'Input'}: ${item.msg}`).join('. ');
    }
    const error = new Error(message);
    error.status = response.status;
    if (response.status === 401 && token && !['/api/auth/login', '/api/auth/register', '/api/auth/logout'].includes(path)) {
      clearSession();
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    throw error;
  }
  return result;
}
