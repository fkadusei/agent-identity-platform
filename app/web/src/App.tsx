import { useCallback, useEffect, useState } from "react";
import {
  authConfig,
  createUser,
  decideApproval,
  deleteUser,
  enroll,
  getAllApprovals,
  getAudit,
  getPrivacyAccess,
  getRoles,
  grantRole,
  listApprovals,
  clearSession,
  SESSION_EXPIRED,
  listUsers,
  loadSession,
  login,
  saveSession,
  resetUserPassword,
  resumeTask,
  revokeRole,
  runTask,
  setUserEnabled,
  type Session,
} from "./api";

type Tab = "console" | "approvals" | "privacy" | "roles" | "audit" | "admin";

// The roles an admin may grant. Kept in step with the API's ASSIGNABLE_ROLES.
const ASSIGNABLE = ["support_rep", "manager", "privacy", "platform_admin"];

// Example tasks, each tied to the tool it exercises, so the console offers only
// what this user's role can actually do — a privacy user sees the PII request, a
// support rep sees the refunds. Without this the privacy path is invisible.
const EXAMPLES: { label: string; task: string; tool: string }[] = [
  { label: "Read a customer profile", task: "Get the profile of customer c-100", tool: "crm.customer.read" },
  { label: "List a customer's orders", task: "List the orders for customer c-100", tool: "crm.orders.list" },
  { label: "Read a ticket", task: "Read ticket t-5001", tool: "tickets.read" },
  { label: "Draft a reply", task: "Draft a reply to ticket t-5001 apologising and saying a refund is on the way", tool: "tickets.reply.draft" },
  { label: "Quote a refund", task: "How much of order o-1001 is refundable?", tool: "refunds.quote" },
  { label: "Refund $25 — allowed", task: "Issue a refund of 25 dollars for order o-1001", tool: "refunds.issue" },
  { label: "Refund $200 — needs a manager", task: "Issue a refund of 200 dollars for order o-1001", tool: "refunds.issue" },
  { label: "Refund $1000 — refused", task: "Issue a refund of 1000 dollars for order o-1001", tool: "refunds.issue" },
  { label: "Read a customer's PII — privacy role + approval", task: "Read the personal data (name, email, phone) of customer c-100", tool: "privacy.pii.read" },
];

// "spiffe://acme.com/ns/agent-platform/sa/agent" -> "sa/agent" (title has the rest).
const shortId = (id: string) => id.split("/").filter(Boolean).slice(-2).join("/");

const STATUS_LABEL: Record<string, string> = {
  ok: "allowed",
  approval_required: "held for approval",
  denied: "denied",
  refused: "refused",
  error: "error",
};

export default function App() {
  // Restored from sessionStorage, so a refresh keeps you signed in.
  const [session, setSessionState] = useState<Session | null>(() => loadSession());
  const setSession = (next: Session | null) => {
    setSessionState(next);
    if (next) saveSession(next);
    else clearSession();
  };
  const [tab, setTab] = useState<Tab>("console");
  const [signupEnabled, setSignupEnabled] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [mode, setMode] = useState<"login" | "enroll">("login");
  // Set when the token expires under a tab that is already open. The tab is kept
  // (unlike an explicit sign-out) so signing back in returns you to what you were
  // doing, rather than to the console.
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const onExpired = () => {
      setSessionState(null);
      setMode("login");
      setNotice(
        "Your session expired (tokens last 5 minutes). Sign in again and you will come " +
          "back to this tab — the page was left open, nothing was lost.",
      );
    };
    window.addEventListener(SESSION_EXPIRED, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED, onExpired);
  }, []);

  useEffect(() => {
    authConfig()
      .then((c) => {
        setSignupEnabled(c.signup_enabled);
        setAgentId(c.agent_id ?? "");
      })
      .catch(() => {});
  }, []);

  const has = (role: string) => !!session?.roles.includes(role);
  const isAdmin = has("platform_admin");
  // Approving is a business decision: the manager role, not platform_admin
  // (which administers users and, deliberately, can call no tools).
  const canApprove = has("manager");
  const tabs: Tab[] = [
    "console",
    "approvals",
    ...(canApprove ? (["privacy"] as Tab[]) : []),
    "roles",
    "audit",
    ...(isAdmin ? (["admin"] as Tab[]) : []),
  ];

  const signOut = () => {
    setSession(null);
    setTab("console");
    setMode("login");
  };

  return (
    <div className="app">
      <header>
        <div>
          <h1>Agent Identity Platform</h1>
          <p className="sub">
            A support copilot with a cryptographic identity — no API keys, policy
            on every action, human approval for high-risk ones.
          </p>
        </div>
        <div className="who">
          {session ? (
            <>
              <span>
                signed in as <b>{session.user}</b>
                {session.tenant && <> · tenant {session.tenant}</>}
                {session.roles.length ? <> · {session.roles.join(", ")}</> : <> · no roles</>}
              </span>
              <button onClick={signOut}>Sign out</button>
            </>
          ) : (
            <span>{mode === "login" ? "sign in to continue" : "create an account"}</span>
          )}
        </div>
      </header>

      {!session && notice && <p className="notice">{notice}</p>}

      {!session &&
        (mode === "login" ? (
          <Login
            onLogin={(s) => {
              setNotice("");
              setSession(s);
            }}
            onEnroll={() => setMode("enroll")}
            signupEnabled={signupEnabled}
          />
        ) : (
          <Enroll onDone={() => setMode("login")} onCancel={() => setMode("login")} />
        ))}

      {session && (
        <>
          <nav>
            {tabs.map((t) => (
              <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </nav>

          <main>
            {tab === "console" && (
              <Console session={session} agentId={agentId} canApprove={canApprove} />
            )}
            {tab === "approvals" && (
              <Approvals session={session} agentId={agentId} canApprove={canApprove} />
            )}
            {tab === "privacy" && <Privacy session={session} />}
            {tab === "roles" && <Roles session={session} />}
            {tab === "audit" && <Audit session={session} />}
            {tab === "admin" && isAdmin && <Admin token={session.token} self={session.user} />}
          </main>
        </>
      )}
    </div>
  );
}

function Login({
  onLogin,
  onEnroll,
  signupEnabled,
}: {
  onLogin: (s: Session) => void;
  onEnroll: () => void;
  signupEnabled: boolean;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await login(username, password));
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="authcard">
      <h2>Sign in</h2>
      <form onSubmit={submit}>
        <input
          placeholder="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
        <input
          type="password"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      {error && <div className="error">{error}</div>}
      <p className="hint">
        Demo accounts — <b>alice</b>/alice123 (support rep), <b>manager</b>/manager123
        (approver), <b>admin</b>/admin123 (platform admin).
      </p>
      {signupEnabled && (
        <p className="hint">
          No account?{" "}
          <button type="button" className="link" onClick={onEnroll}>
            Create one
          </button>{" "}
          — an admin will grant you a role.
        </p>
      )}
    </section>
  );
}

function Enroll({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [form, setForm] = useState({
    username: "",
    email: "",
    firstName: "",
    lastName: "",
    password: "",
  });
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await enroll(form);
      setDone(true);
    } catch (err) {
      setError(String(err));
    }
  };

  if (done) {
    return (
      <section className="authcard">
        <h2>Account created</h2>
        <p className="hint">
          Your account has <b>no roles</b> yet. Ask an admin to grant you access, then sign in.
        </p>
        <button onClick={onDone}>Back to sign in</button>
      </section>
    );
  }

  return (
    <section className="authcard">
      <h2>Create an account</h2>
      <form onSubmit={submit}>
        <input placeholder="username" value={form.username} onChange={set("username")} />
        <input placeholder="email" value={form.email} onChange={set("email")} />
        <input placeholder="first name" value={form.firstName} onChange={set("firstName")} />
        <input placeholder="last name" value={form.lastName} onChange={set("lastName")} />
        <input
          type="password"
          placeholder="password (min 8)"
          value={form.password}
          onChange={set("password")}
        />
        <button>Create account</button>
      </form>
      {error && <div className="error">{error}</div>}
      <p className="hint">
        New accounts start with <b>no roles</b> and can do nothing until an admin grants one.
      </p>
      <button type="button" className="link" onClick={onCancel}>
        Back to sign in
      </button>
    </section>
  );
}

function Console({
  session,
  agentId,
  canApprove,
}: {
  session: Session;
  agentId: string;
  canApprove: boolean;
}) {
  const [task, setTask] = useState("Issue a refund of 200 dollars for order o-1001");
  const [asked, setAsked] = useState("");
  const [outcome, setOutcome] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // The tools the caller's roles permit, from the policy (via login).
  const canRun = session.tools.length > 0;

  const run = async () => {
    setBusy(true);
    setError("");
    setOutcome(null);
    setAsked(task);
    try {
      setOutcome(await runTask(task, session.token));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // An approver decides and the run continues in one step.
  const decide = async (approved: boolean) => {
    setBusy(true);
    setError("");
    try {
      await decideApproval(outcome.approval_id, approved, session.token);
      setOutcome(await resumeTask(outcome.thread_id, approved, session.token));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // The requester continues once someone else has approved. Safe to press: if
  // the approval is still pending, policy simply holds the run again.
  const resume = async () => {
    setBusy(true);
    setError("");
    try {
      setOutcome(await resumeTask(outcome.thread_id, true, session.token));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>Ask the agent</h2>
      {!canRun && (
        <p className="hint">
          Your role cannot call any tools. Ask an admin to grant you a role (for
          example <b>support_rep</b> or <b>read_only</b>).
        </p>
      )}
      {canRun && (
        <p className="hint">
          Your role may call: {session.tools.map((t) => <code key={t}>{t}</code>).reduce(
            (acc, el) => (acc === null ? el : [acc, " ", el]), null as any)}
        </p>
      )}
      {canApprove && (
        <p className="hint">
          You are an approver: the actions you decide are in the <b>Approvals</b>{" "}
          tab, not here. Running a task is what the requester does.
        </p>
      )}
      {canRun && (
        <div className="examples">
          {EXAMPLES.filter((e) => session.tools.includes(e.tool)).map((e) => (
            <button key={e.label} className="chip" onClick={() => setTask(e.task)}>
              {e.label}
            </button>
          ))}
        </div>
      )}
      <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={2} />
      <button disabled={!canRun || busy} onClick={run}>
        {busy ? "Running…" : "Run"}
      </button>
      {error && <div className="error">{error}</div>}
      {outcome && (
        <ResultCard
          asked={asked}
          session={session}
          agentId={agentId}
          outcome={outcome}
          busy={busy}
          canApprove={canApprove}
          onDecide={decide}
          onResume={resume}
        />
      )}
    </section>
  );
}

function ResultCard({
  asked,
  session,
  agentId,
  outcome,
  busy,
  canApprove,
  onDecide,
  onResume,
}: {
  asked: string;
  session: Session;
  agentId: string;
  outcome: any;
  busy: boolean;
  canApprove: boolean;
  onDecide: (approved: boolean) => void;
  onResume: () => void;
}) {
  const held = outcome.status === "approval_required";
  const [decided, setDecided] = useState<string | null>(null);

  // While held, watch the approval so the requester's card updates the moment
  // someone else decides (e.g. a manager in another tab).
  useEffect(() => {
    if (!held) return;
    const tick = async () => {
      try {
        const all = await getAllApprovals(session.token);
        const mine = all.find((a: any) => a.id === outcome.approval_id);
        if (mine && mine.status !== "pending") setDecided(mine.status);
      } catch {
        /* transient; try again next tick */
      }
    };
    const t = setInterval(tick, 4000);
    return () => clearInterval(t);
  }, [held, outcome.approval_id, session.token]);

  return (
    <div className="card result">
      <div className={`status ${outcome.status}`}>
        {STATUS_LABEL[outcome.status] ?? outcome.status}
      </div>

      <h3>What just happened</h3>
      <ol className="steps">
        <li>
          You asked: <span className="q">“{asked}”</span>
        </li>
        <li>
          The agent authenticated as{" "}
          <code title={agentId}>{shortId(agentId) || "agent"}</code> and exchanged your
          token, acting for <b>{session.user}</b>
        </li>
        {outcome.tool && (
          <li>
            It called <code>{outcome.tool}</code>
          </li>
        )}
        <li>
          {outcome.status === "error" ? (
            <>The run stopped — {outcome.reason}</>
          ) : (
            <>
              Policy decided <b>{STATUS_LABEL[outcome.status] ?? outcome.status}</b>
              {outcome.reason && <> — {outcome.reason}</>}
            </>
          )}
        </li>
      </ol>

      <div className="chain" title={agentId}>
        <span className="node">agent {shortId(agentId) || "agent"}</span>
        <span className="arrow">→</span>
        <span className="node">user {session.user}</span>
        {outcome.tool && (
          <>
            <span className="arrow">→</span>
            <span className="node">tool {outcome.tool}</span>
          </>
        )}
      </div>

      {held && (
        <div className="approval">
          {decided === "approved" && !canApprove ? (
            <>
              <p>
                Approved by a manager. <b>Resume</b> to let the agent finish.
              </p>
              <button disabled={busy} onClick={onResume}>
                Resume now
              </button>
            </>
          ) : decided === "denied" && !canApprove ? (
            <p className="reason">
              Denied by a manager — the agent will not perform this action.
            </p>
          ) : canApprove ? (
            <div className="row">
              <span>
                Held for approval <code>{outcome.approval_id}</code> — you can decide it.
              </span>
              <div>
                <button disabled={busy} onClick={() => onDecide(true)}>
                  Approve
                </button>
                <button disabled={busy} onClick={() => onDecide(false)}>
                  Deny
                </button>
              </div>
            </div>
          ) : (
            <div className="row">
              <span>
                Held for approval <code>{outcome.approval_id}</code> — a manager must
                decide it in the Approvals tab.
              </span>
              <button disabled={busy} onClick={onResume}>
                Resume when approved
              </button>
            </div>
          )}
        </div>
      )}

      {!held && outcome.result && Object.keys(outcome.result).length > 0 && (
        <>
          <h3>Result</h3>
          <pre>{JSON.stringify(outcome.result, null, 2)}</pre>
        </>
      )}
    </div>
  );
}

function Approvals({
  session,
  agentId,
  canApprove,
}: {
  session: Session;
  agentId: string;
  canApprove: boolean;
}) {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setItems(await listApprovals(session.token));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const decide = async (id: string, approved: boolean) => {
    try {
      await decideApproval(id, approved, session.token);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <section>
      <h2>Approval queue</h2>
      {!canApprove && (
        <p className="hint">
          Deciding requires the <b>manager</b> role. Approving here records the
          decision; the requester resumes the run from their console.
        </p>
      )}
      {error && <div className="error">{error}</div>}
      {items.length === 0 && (
        <p className="hint">
          {canApprove ? (
            <>
              Nothing pending. <b>This is where you act.</b> To get something to
              approve, sign in as <b>alice</b> (or <b>bella</b>, or <b>priya</b> for
              PII) in another tab and ask for something that needs approval — a
              refund of 200, say. It will appear here.
            </>
          ) : (
            <>Nothing pending. A held action appears here while the agent waits.</>
          )}
        </p>
      )}
      {items.map((a) => (
        <div className="card" key={a.id}>
          <div className="row">
            <b>{a.tool}</b>
            <code>{a.id}</code>
          </div>
          <div className="chain" title={a.agent}>
            <span className="node">agent {shortId(a.agent || agentId) || "agent"}</span>
            <span className="arrow">→</span>
            <span className="node">user {a.user}</span>
            <span className="arrow">→</span>
            <span className="node">tool {a.tool}</span>
          </div>
          <p className="reason">{a.reason}</p>
          <pre>{JSON.stringify(a.args, null, 2)}</pre>
          <div className="row">
            <span className="muted">requested by {a.user}</span>
            <div>
              <button disabled={!canApprove} onClick={() => decide(a.id, true)}>
                Approve
              </button>
              <button disabled={!canApprove} onClick={() => decide(a.id, false)}>
                Deny
              </button>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

function Admin({ token, self }: { token: string; self: string }) {
  const [users, setUsers] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setUsers(await listUsers(token));
    } catch (e) {
      setError(String(e));
    }
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const toggleRole = async (u: any, role: string, held: boolean) => {
    try {
      held ? await revokeRole(u.id, role, token) : await grantRole(u.id, role, token);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const toggleEnabled = async (u: any) => {
    try {
      await setUserEnabled(u.id, !u.enabled, token);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const reset = async (u: any) => {
    const pw = window.prompt(`New password for ${u.username} (min 8):`);
    if (!pw) return;
    try {
      await resetUserPassword(u.id, pw, token);
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (u: any) => {
    if (!window.confirm(`Delete ${u.username}? This cannot be undone.`)) return;
    try {
      await deleteUser(u.id, token);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <section>
      <div className="row">
        <h2>Users</h2>
        <button onClick={() => setCreating(!creating)}>{creating ? "Cancel" : "New user"}</button>
      </div>
      {error && <div className="error">{error}</div>}
      {creating && (
        <CreateUser
          token={token}
          onCreated={() => {
            setCreating(false);
            refresh();
          }}
        />
      )}
      <table className="users">
        <thead>
          <tr>
            <th>user</th>
            <th>roles</th>
            <th>status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>
                <b>{u.username}</b>
                <br />
                <span className="muted">{u.email}</span>
              </td>
              <td>
                {ASSIGNABLE.map((r) => (
                  <label key={r} className="role">
                    <input
                      type="checkbox"
                      checked={u.roles.includes(r)}
                      onChange={() => toggleRole(u, r, u.roles.includes(r))}
                    />{" "}
                    {r}
                  </label>
                ))}
              </td>
              <td>{u.enabled ? "enabled" : <span className="muted">disabled</span>}</td>
              <td className="actions">
                <button onClick={() => toggleEnabled(u)}>{u.enabled ? "Disable" : "Enable"}</button>
                <button onClick={() => reset(u)}>Reset password</button>
                <button disabled={u.username === self} onClick={() => remove(u)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function CreateUser({ token, onCreated }: { token: string; onCreated: () => void }) {
  const [form, setForm] = useState({ username: "", email: "", password: "", tenant: "acme" });
  const [roles, setRoles] = useState<string[]>([]);
  const [error, setError] = useState("");

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });
  const toggle = (r: string) =>
    setRoles(roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await createUser({ ...form, roles }, token);
      onCreated();
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <form className="createuser" onSubmit={submit}>
      <input placeholder="username" value={form.username} onChange={set("username")} />
      <input placeholder="email" value={form.email} onChange={set("email")} />
      <input
        type="password"
        placeholder="password (min 8)"
        value={form.password}
        onChange={set("password")}
      />
      <input
        placeholder="tenant"
        value={form.tenant}
        onChange={set("tenant")}
        title="The tenant this account is scoped to"
      />
      <div>
        {ASSIGNABLE.map((r) => (
          <label key={r} className="role">
            <input type="checkbox" checked={roles.includes(r)} onChange={() => toggle(r)} /> {r}
          </label>
        ))}
      </div>
      <button>Create</button>
      {error && <div className="error">{error}</div>}
    </form>
  );
}

function Audit({ session }: { session: Session }) {
  const [events, setEvents] = useState<any[]>([]);
  const [stale, setStale] = useState(false);
  useEffect(() => {
    // Keep the last good timeline when a refresh fails, and say it is stale. The
    // previous version caught the failure and set an empty array, so a dropped
    // port-forward or an expired token rendered "No events yet" — which reads as the
    // audit trail having been lost, rather than as not having been re-read.
    const load = async () => {
      try {
        setEvents(await getAudit(session.token));
        setStale(false);
      } catch {
        setStale(true);
      }
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [session.token]);

  return (
    <section>
      <h2>Audit timeline</h2>
      <p className="hint">
        One record per event, keyed by identity. Tokens and personal data are
        redacted before anything is written.
        {stale && <> <b className="stale">Not updating — the last good view is below.</b></>}
      </p>
      <div className="timeline">
        {events.map((e, i) => (
          <div className="event" key={i}>
            <code className="ev">{e.event}</code>
            <span className="meta">
              {e.spiffe_id && <>agent <b>{shortId(e.spiffe_id)}</b> · </>}
              {e.sub && <>user <b>{e.sub}</b> · </>}
              {e.tool && <>tool <code>{e.tool}</code> · </>}
              {e.decision && <>decision <b>{e.decision}</b></>}
            </span>
          </div>
        ))}
        {events.length === 0 && <p className="hint">No events yet.</p>}
      </div>
    </section>
  );
}

// Personal-data access: the one place where a read is as sensitive as a change,
// so it gets its own view rather than a row in the generic approval queue.
function Privacy({ session }: { session: Session }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () =>
      getPrivacyAccess(session.token)
        .then((d) => {
          setData(d);
          setError("");
        })
        .catch((e) => setError(String(e)));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [session.token]);

  const head = <h2>Personal-data access</h2>;
  if (error)
    return (
      <section>
        {head}
        <div className="error">{error}</div>
      </section>
    );
  if (!data)
    return (
      <section>
        {head}
        <p className="hint">Loading…</p>
      </section>
    );

  const at = (ts: number) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
  const outcome = (a: any) => STATUS_LABEL[a.decision] ?? a.decision ?? a.event;

  return (
    <section>
      {head}
      <p className="hint">
        Reading personal data needs the <b>privacy</b> role <b>and</b> your approval.
        Every attempt that reached the tool server is here — held, allowed, or
        refused. A request from a role with no PII access at all is stopped by the
        agent before the tool server sees it, so it does not appear below. Scoped to
        tenant <b>{data.tenant}</b>.
      </p>

      <h3>Access attempts</h3>
      <div className="timeline">
        {data.access.map((a: any, i: number) => (
          <div className="event" key={i}>
            <code className="ev">{outcome(a)}</code>
            <span className="meta">
              user <b>{a.user}</b> · tool <code>{a.tool}</code>
              {a.reason && <> · {a.reason}</>} · {at(a.at)}
              {a.policy_version && <> · policy <b>{a.policy_version}</b></>}
            </span>
          </div>
        ))}
        {data.access.length === 0 && (
          <p className="hint">No one has tried to read personal data yet.</p>
        )}
      </div>

      <h3>Approvals</h3>
      <div className="timeline">
        {data.approvals.map((a: any) => (
          <div className="event" key={a.id}>
            <code className="ev">{a.status}</code>
            <span className="meta">
              {a.args?.customer_id && (
                <>
                  customer <b>{a.args.customer_id}</b> ·{" "}
                </>
              )}
              asked by <b>{a.user}</b>
              {a.reason && <> · {a.reason}</>} · {at(a.created_at)}
              {a.approver && (
                <>
                  {" "}
                  · decided by <b>{a.approver}</b> {at(a.decided_at)}
                </>
              )}
              {a.note && <> — “{a.note}”</>}
            </span>
          </div>
        ))}
        {data.approvals.length === 0 && (
          <p className="hint">No personal-data approvals yet.</p>
        )}
      </div>
    </section>
  );
}

function Roles({ session }: { session: Session }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getRoles(session.token)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [session.token]);

  if (error)
    return (
      <section>
        <h2>Roles &amp; tools</h2>
        <div className="error">{error}</div>
      </section>
    );
  if (!data)
    return (
      <section>
        <h2>Roles &amp; tools</h2>
        <p className="hint">Loading…</p>
      </section>
    );

  const roles: string[] = Object.keys(data.roles);
  const tools: string[] = data.tools;
  const mine: string[] = data.you?.roles ?? [];
  const may = (role: string, tool: string) => (data.roles[role] ?? []).includes(tool);

  return (
    <section>
      <h2>Roles &amp; tools</h2>
      <p className="hint">
        Which role may call which tool — the policy itself, the same table the tool
        server enforces. This is <b>tenant {data.you?.tenant ?? "—"}</b>: a tenant
        can replace a role's tools, so the same role name may differ for another
        customer. Your roles are highlighted.
      </p>
      <div className="matrixwrap">
        <table className="matrix">
          <thead>
            <tr>
              <th className="toolcol">tool</th>
              {roles.map((r) => (
                <th key={r} className={mine.includes(r) ? "mine" : ""}>
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tools.map((t) => (
              <tr key={t}>
                <td className="toolcol">
                  <code>{t}</code>
                </td>
                {roles.map((r) => (
                  <td key={r} className={mine.includes(r) ? "mine" : ""}>
                    {may(r, t) ? <span className="yes">✓</span> : <span className="no">·</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        Refunds: up to <b>${data.limits?.auto}</b> allowed, up to{" "}
        <b>${data.limits?.approval}</b> needs a manager, above that refused. PII needs
        the <b>privacy</b> role <b>and</b> approval. Everything is scoped to your
        tenant, and <b>platform_admin</b> calls no tools and does not approve.
      </p>
    </section>
  );
}
