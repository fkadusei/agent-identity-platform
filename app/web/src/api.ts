// Minimal API client. In production the UI is same-origin; in dev, Vite proxies.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

// A 401 on a call that *carried* a token means the token is no longer good. The
// demo's user tokens live 5 minutes (the realm's `accessTokenLifespan`), so a tab
// left open meets this. It is worth announcing rather than letting each page fail
// on its own: the audit timeline used to catch it and render "No events yet", which
// reads as data loss instead of an expired session. The app listens for this, drops
// the session and explains what happened.
export const SESSION_EXPIRED = "agent-platform:session-expired";

async function request(path: string, init: RequestInit = {}, retried = false): Promise<any> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      // `init` first, then headers — otherwise init.headers would overwrite the
      // merged headers and drop Content-Type (FastAPI would then 422 the body).
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  } catch {
    // fetch only rejects on a network-level failure (server down, dropped
    // port-forward, or a CORS/blocked request) — never on an HTTP error status.
    const where = BASE || window.location.origin;
    throw new Error(
      `Cannot reach the API at ${where}. Is the server running — or your ` +
        `\`kubectl port-forward svc/api 8080:8080\` still alive?`,
    );
  }
  const sentHeaders = init.headers as Record<string, string> | undefined;
  // Only an *authenticated* call can expire: a 401 from /auth/login is a wrong
  // password, and signing the user out over it would be nonsense.
  const carriedToken = Boolean(sentHeaders?.Authorization);
  const body = await res.json().catch(() => ({}));
  const detail = typeof body?.detail === "string" ? body.detail : "";
  // The API answers 403 for two unrelated things: a token that is invalid or expired
  // ("invalid token: Signature has expired", measured), and a caller who is properly
  // authenticated but lacks the role. Only the first should renew or sign anyone out,
  // and the status code cannot tell them apart — so this matches the messages the API
  // emits for token problems. (401 is handled too: the API uses it when no token
  // arrived.)
  const tokenTrouble =
    res.status === 401 ||
    (res.status === 403 && /invalid token|missing bearer token|expired|not enough segments/i.test(detail));
  if (carriedToken && tokenTrouble) {
    // The access token has expired. Renew silently from the refresh token and try
    // again once — that is what keeps a five-minute token from being a five-minute
    // session. Only when the renewal itself fails do we send the person to sign in.
    if (!retried) {
      const renewed = await renewSession();
      if (renewed) {
        return request(
          path,
          { ...init, headers: { ...sentHeaders, Authorization: `Bearer ${renewed.token}` } },
          true,
        );
      }
    }
    clearSession();
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED));
    throw new Error("Your session expired — sign in again to continue.");
  }
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body;
}

// FastAPI's `detail` is a string for HTTPException, but an array of objects for
// validation errors — stringifying that array yields "[object Object]".
function errorMessage(body: any, status: number): string {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join("; ");
  }
  return `HTTP ${status}`;
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });
const json = (method: string, token: string, body?: any): RequestInit => ({
  method,
  headers: auth(token),
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

// --- auth + enrollment -----------------------------------------------------
export type Session = {
  user: string;
  roles: string[];
  tenant: string;
  tools: string[];
  expiresAt: number;
  token: string;
  // The access token lives five minutes; the refresh token renews it silently.
  // Keycloak rotates the refresh token on every use, so this value changes each time.
  refreshToken: string;
  refreshExpiresAt: number;
};

export const authConfig = () => request("/auth/config");

// One shape for a login and a renewal — both are "here is a session". The API
// speaks OAuth and returns `access_token`; the app works with `token`. Normalise
// here so callers never accidentally send "Bearer undefined".
const normaliseSession = (r: any): Session => {
  if (!r?.access_token) throw new Error("the session response did not include an access token");
  return {
    user: r.user,
    roles: r.roles ?? [],
    tenant: r.tenant ?? "",
    tools: r.tools ?? [],
    expiresAt: r.expires_at ?? 0,
    token: r.access_token,
    refreshToken: r.refresh_token ?? "",
    refreshExpiresAt: r.refresh_expires_at ?? 0,
  };
};

export const login = async (username: string, password: string): Promise<Session> => {
  const r = await request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  return normaliseSession(r);
};

export const refreshSession = async (refreshToken: string): Promise<Session> => {
  const r = await request("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  return normaliseSession(r);
};

// --- the session survives a page refresh -----------------------------------
// sessionStorage, not localStorage: it lives for the tab and dies with it. The
// access token may have expired between loads — the stored refresh token is what
// brings the session back, so a page reload renews silently instead of landing on
// the sign-in screen. A session is dropped only once its refresh window has passed.
const SESSION_KEY = "agent-platform.session";

export function saveSession(s: Session): void {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(s));
  } catch {
    /* private mode etc. — the session just won't persist */
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    const shaped = s && s.token && Array.isArray(s.roles) && Array.isArray(s.tools);
    // Keep the session while the *refresh* token is valid, even if the access token
    // has already expired — the App renews it on load. Fall back to the access
    // token's own expiry for a session stored by an older build.
    const liveUntil = s?.refreshExpiresAt || s?.expiresAt || 0;
    if (!shaped || (liveUntil && Date.now() / 1000 > liveUntil)) {
      clearSession();
      return null;
    }
    return s;
  } catch {
    return null;
  }
}

// One renewal at a time. The refresh token is rotated on every use, so two
// concurrent renewals would race and one would be rejected — everyone shares the
// same promise. Returns null when there is nothing to renew with, or the renewal
// failed (the refresh window passed, or the session was revoked).
let renewalInFlight: Promise<Session | null> | null = null;

export async function renewSession(): Promise<Session | null> {
  const s = loadSession();
  if (!s?.refreshToken) return null;
  if (!renewalInFlight) {
    renewalInFlight = refreshSession(s.refreshToken)
      .then((next) => {
        saveSession(next);
        return next;
      })
      .catch(() => {
        clearSession();
        return null;
      })
      .finally(() => {
        renewalInFlight = null;
      });
  }
  return renewalInFlight;
}

export const enroll = (form: {
  username: string;
  email: string;
  password: string;
  firstName?: string;
  lastName?: string;
}) => request("/enroll", { method: "POST", body: JSON.stringify(form) });

// --- agent tasks + approvals ----------------------------------------------
export const runTask = (task: string, token: string) =>
  request("/tasks", { method: "POST", headers: auth(token), body: JSON.stringify({ task }) });

// One resume endpoint, two kinds of answer: an approval decides a permission,
// a clarification supplies a fact. They are never the same request.
export type ResumeDecision = { approved: boolean } | { values: Record<string, string> };

export const resumeTask = (thread_id: string, decision: ResumeDecision, token: string) =>
  request("/tasks/resume", {
    method: "POST",
    headers: auth(token),
    body: JSON.stringify({ thread_id, ...decision }),
  });

// The approval queue is tenant-scoped, so it needs the caller's token.
export const listApprovals = (token: string) =>
  request("/approvals?status=pending", { headers: auth(token) });

// All approvals (any status) — used to watch a held run flip to decided.
export const getAllApprovals = (token: string) =>
  request("/approvals", { headers: auth(token) });

export const decideApproval = (id: string, approved: boolean, token: string, note = "") =>
  request(`/approvals/${id}/decision`, {
    method: "POST",
    headers: auth(token),
    body: JSON.stringify({ approved, note }),
  });

// The audit timeline, narrowable by event, tool, or user. The API requires a
// token and scopes the trail to the caller's tenant.
export const getAudit = (
  token: string,
  filters: { event?: string; tool?: string; sub?: string } = {},
) => {
  const q = new URLSearchParams({ limit: "100", ...filters }).toString();
  return request(`/audit?${q}`, { headers: auth(token) });
};

// Personal-data access and the approvals behind it (manager only).
export const getPrivacyAccess = (token: string) =>
  request("/privacy/access", { headers: auth(token) });

// The role -> tool matrix, straight from the policy.
export const getRoles = (token: string) => request("/roles", { headers: auth(token) });

// --- admin: user management (requires the platform_admin role) -------------
export const listUsers = (token: string) => request("/admin/users", { headers: auth(token) });

export const createUser = (
  form: { username: string; email: string; password: string; tenant: string; roles: string[] },
  token: string,
) => request("/admin/users", json("POST", token, form));

export const grantRole = (id: string, role: string, token: string) =>
  request(`/admin/users/${id}/roles`, json("POST", token, { role }));

export const revokeRole = (id: string, role: string, token: string) =>
  request(`/admin/users/${id}/roles/${role}`, json("DELETE", token));

export const setUserEnabled = (id: string, enabled: boolean, token: string) =>
  request(`/admin/users/${id}/enabled`, json("POST", token, { enabled }));

export const resetUserPassword = (id: string, password: string, token: string) =>
  request(`/admin/users/${id}/password`, json("POST", token, { password }));

export const deleteUser = (id: string, token: string) =>
  request(`/admin/users/${id}`, json("DELETE", token));
