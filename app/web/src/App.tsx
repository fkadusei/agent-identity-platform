import { useCallback, useEffect, useState } from "react";
import {
  decideApproval,
  getAudit,
  listApprovals,
  login,
  resumeTask,
  runTask,
} from "./api";

type Tab = "console" | "approvals" | "audit";

export default function App() {
  const [user, setUser] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [tab, setTab] = useState<Tab>("console");
  const [error, setError] = useState("");

  const doLogin = async (u: string) => {
    setError("");
    try {
      const r = await login(u);
      setUser(r.user);
      setToken(r.access_token);
    } catch (e) {
      setError(String(e));
    }
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
          <span>{user ? <>signed in as <b>{user}</b></> : "not signed in"}</span>
          <button onClick={() => doLogin("alice")}>Sign in as alice</button>
          <button onClick={() => doLogin("manager")}>as manager</button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <nav>
        {(["console", "approvals", "audit"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      <main>
        {tab === "console" && <Console token={token} />}
        {tab === "approvals" && <Approvals token={token} user={user} />}
        {tab === "audit" && <Audit />}
      </main>
    </div>
  );
}

function Console({ token }: { token: string }) {
  const [task, setTask] = useState("Issue a refund of 200 dollars for order o-1001");
  const [outcome, setOutcome] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setError("");
    setOutcome(null);
    try {
      setOutcome(await runTask(task, token));
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
      {!token && <p className="hint">Sign in as alice first.</p>}
      <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={2} />
      <button disabled={!token || busy} onClick={run}>
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

function Approvals({ token, user }: { token: string; user: string | null }) {
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
      await decideApproval(id, approved, token);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <section>
      <h2>Approval queue</h2>
      {user !== "manager" && <p className="hint">Sign in as manager to approve or deny.</p>}
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
              <button disabled={user !== "manager"} onClick={() => decide(a.id, true)}>
                Approve
              </button>
              <button disabled={user !== "manager"} onClick={() => decide(a.id, false)}>
                Deny
              </button>
            </div>
          </div>
        </div>
      ))}
    </section>
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
