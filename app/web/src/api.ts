// Minimal API client. In production the UI is same-origin; in dev, Vite proxies.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function request(path: string, init: RequestInit = {}): Promise<any> {
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
  const body = await res.json().catch(() => ({}));
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
export const authConfig = () => request("/auth/config");

export const login = (username: string, password: string) =>
  request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });

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

export const resumeTask = (thread_id: string, approved: boolean) =>
  request("/tasks/resume", { method: "POST", body: JSON.stringify({ thread_id, approved }) });

export const listApprovals = () => request("/approvals?status=pending");

export const decideApproval = (id: string, approved: boolean, token: string, note = "") =>
  request(`/approvals/${id}/decision`, {
    method: "POST",
    headers: auth(token),
    body: JSON.stringify({ approved, note }),
  });

export const getAudit = () => request("/audit?limit=100");

// --- admin: user management (requires the platform_admin role) -------------
export const listUsers = (token: string) => request("/admin/users", { headers: auth(token) });

export const createUser = (
  form: { username: string; email: string; password: string; roles: string[] },
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
