// Minimal API client. In production the UI is same-origin; in dev, Vite proxies.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function request(path: string, init: RequestInit = {}): Promise<any> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
  return body;
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

export const login = (user: string) =>
  request("/demo/login", { method: "POST", body: JSON.stringify({ user }) });

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
