import { useCallback, useEffect, useState } from "react";
import {
  authConfig,
  createUser,
  decideApproval,
  deleteUser,
  enroll,
  getAudit,
  grantRole,
  listApprovals,
  listUsers,
  login,
  resetUserPassword,
  resumeTask,
  revokeRole,
  runTask,
  setUserEnabled,
  type Session,
} from "./api";

type Tab = "console" | "approvals" | "audit" | "admin";

// The roles an admin may grant. Kept in step with the API's ASSIGNABLE_ROLES.
const ASSIGNABLE = ["support_rep", "manager", "privacy", "platform_admin"];

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [tab, setTab] = useState<Tab>("console");
  const [signupEnabled, setSignupEnabled] = useState(false);
  const [mode, setMode] = useState<"login" | "enroll">("login");

  useEffect(() => {
    authConfig()
      .then((c) => setSignupEnabled(c.signup_enabled))
      .catch(() => {});
  }, []);

  const has = (role: string) => !!session?.roles.includes(role);
  const isAdmin = has("platform_admin");
  const canApprove = has("manager") || isAdmin;
  const tabs: Tab[] = ["console", "approvals", "audit", ...(isAdmin ? (["admin"] as Tab[]) : [])];

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
                {session.roles.length ? <> · {session.roles.join(", ")}</> : <> · no roles</>}
              </span>
              <button onClick={signOut}>Sign out</button>
            </>
          ) : (
            <span>{mode === "login" ? "sign in to continue" : "create an account"}</span>
          )}
        </div>
      </header>

      {!session &&
        (mode === "login" ? (
          <Login
            onLogin={setSession}
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
            {tab === "console" && <Console session={session} />}
            {tab === "approvals" && <Approvals session={session} canApprove={canApprove} />}
            {tab === "audit" && <Audit />}
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

function Console({ session }: { session: Session }) {
  const [task, setTask] = useState("Issue a refund of 200 dollars for order o-1001");
  const [outcome, setOutcome] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const canRun = session.roles.includes("support_rep");

  const run = async () => {
    setBusy(true);
    setError("");
    setOutcome(null);
    try {
      setOutcome(await runTask(task, session.token));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const resume = async (approved: boolean) => {
    try {
      setOutcome(await resumeTask(outcome.thread_id, approved));
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <section>
      <h2>Ask the agent</h2>
      {!canRun && (
        <p className="hint">
          The agent acts on behalf of a support rep. Sign in as a user with the{" "}
          <b>support_rep</b> role to run tasks; approvers decide them.
        </p>
      )}
      <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={2} />
      <button disabled={!canRun || busy} onClick={run}>
        {busy ? "Running…" : "Run"}
      </button>
      {error && <div className="error">{error}</div>}
      {outcome && (
        <div className="card">
          <div className={`status ${outcome.status}`}>{outcome.status}</div>
          {outcome.tool && <p>tool: <code>{outcome.tool}</code></p>}
          {outcome.reason && <p className="reason">{outcome.reason}</p>}
          {outcome.status === "approval_required" && (
            <div className="approval">
              <p>
                Held for approval <code>{outcome.approval_id}</code> — go to the
                Approvals tab.
              </p>
              <button onClick={() => resume(true)}>Resume (approved)</button>
            </div>
          )}
          {outcome.result && <pre>{JSON.stringify(outcome.result, null, 2)}</pre>}
        </div>
      )}
    </section>
  );
}

function Approvals({ session, canApprove }: { session: Session; canApprove: boolean }) {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setItems(await listApprovals());
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
          Deciding requires the <b>manager</b> (or platform_admin) role.
        </p>
      )}
      {error && <div className="error">{error}</div>}
      {items.length === 0 && <p className="hint">Nothing pending.</p>}
      {items.map((a) => (
        <div className="card" key={a.id}>
          <div className="row">
            <b>{a.tool}</b>
            <code>{a.id}</code>
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
  const [form, setForm] = useState({ username: "", email: "", password: "" });
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

function Audit() {
  const [events, setEvents] = useState<any[]>([]);
  useEffect(() => {
    const load = async () => setEvents(await getAudit().catch(() => []));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <section>
      <h2>Audit timeline</h2>
      <p className="hint">
        One record per event, keyed by identity. Tokens and personal data are
        redacted before anything is written.
      </p>
      <div className="timeline">
        {events.map((e, i) => (
          <div className="event" key={i}>
            <code className="ev">{e.event}</code>
            <span className="meta">
              {e.spiffe_id && <>agent <b>{short(e.spiffe_id)}</b> · </>}
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

const short = (id: string) => id.split("/").pop();
