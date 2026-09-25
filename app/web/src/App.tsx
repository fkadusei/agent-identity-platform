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
/** Every timestamp in the UI goes through this, so they read the same everywhere. */
const at = (ts: number | undefined) => (ts ? new Date(ts * 1000).toLocaleString() : "—");

/** One labelled chip: the caption is a micro-label, the value carries the emphasis. */
type Kind = "agent" | "user" | "tool" | "policy" | "when" | "tenant" | "decision" | "";

/** One labelled chip. `kind` is what gives it a colour: the colour says which sort of
    fact it is (who, which tool, which policy), not decoration. */
const FACT = (k: string, v: any, kind: Kind = "") => (
  <span className={kind ? `fact ${kind}` : "fact"}>
    <span className="k">{k}</span>
    <span className="v">{v}</span>
  </span>
);

/** Colour by outcome, so a trail can be scanned rather than read. */
const tone = (s: any) => {
  const v = String(s ?? "").toLowerCase();
  if (/deny|denied|refus|error|fail/.test(v)) return "bad";
  if (/approval|held|require|pending|limit/.test(v)) return "warn";
  if (/allow|ok|issued|approved|success/.test(v)) return "ok";
  return "";
};

const shortId = (id: string) => id.split("/").filter(Boolean).slice(-2).join("/");

const STATUS_LABEL: Record<string, string> = {
  ok: "allowed",
  approval_required: "held for approval",
  clarification_required: "waiting for an answer",
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
  // The roles an admin may grant come from the api, which is the side that has to know
  // them. This used to be a list here too, and the two drifted: `billing` and
  // `read_only` existed in the policy and the realm but not in either list, so a user
  // holding one of them signed in as "no roles".
  const [assignable, setAssignable] = useState<string[]>([]);
  const [mode, setMode] = useState<"login" | "enroll">("login");
  // Set when the token expires under a tab that is already open. The tab is kept
  // (unlike an explicit sign-out) so signing back in returns you to what you were
  // doing, rather than to the console.
  const [notice, setNotice] = useState("");

  const expire = useCallback(() => {
    setSessionState(null);
    setMode("login");
    setNotice(
      "Your session expired (tokens last 5 minutes). Sign in again and you will come " +
        "back to this tab — the page was left open, nothing was lost.",
    );
  }, []);

  // React to a token the API rejects...
  useEffect(() => {
    window.addEventListener(SESSION_EXPIRED, expire);
    return () => window.removeEventListener(SESSION_EXPIRED, expire);
  }, [expire]);

  // ...and expire on time from the session's own deadline, which the API supplies
  // (`expires_at`). That way the UI does not have to infer an expired session from a
  // status code at all — the 403 above is a backstop for the token being rejected
  // before this fires.
  useEffect(() => {
    if (!session) return;
    const t = setTimeout(expire, Math.max(session.expiresAt * 1000 - Date.now() - 5000, 0));
    return () => clearTimeout(t);
  }, [session, expire]);

  useEffect(() => {
    authConfig()
      .then((c) => {
        setSignupEnabled(c.signup_enabled);
        setAgentId(c.agent_id ?? "");
        setAssignable(c.roles ?? []);
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
    <>
      {/*
        A full-width bar, not a row inside the centred column: "top left" should mean
        the corner of the page, and the column's left edge sits far from it on a wide
        screen. Sign out is flush left, the session it ends is flush right, and the bar
        stays put while the page scrolls so the control is always where it was.
      */}
      {session && (
        <header className="topbar" data-tab={tab}>
          <span className="facts">
            {FACT("signed in", session.user, "user")}
            {session.tenant && FACT("tenant", session.tenant, "tenant")}
            {session.roles.length ? (
              session.roles.map((r) => (
                <span className={`fact role-${r}`} key={r}>
                  <span className="k">role</span>
                  <span className="v">{r}</span>
                </span>
              ))
            ) : (
              FACT("roles", "none")
            )}
          </span>
          <button className="ghost" onClick={signOut}>Sign out</button>
        </header>
      )}

      <div className="app" data-tab={tab}>
        <div className="brand">
        <span className="mark" aria-hidden="true">AI</span>
        <div>
          <h1>Agent Identity Platform</h1>
          <p className="sub">
            A support copilot with a cryptographic identity — no API keys, policy
            on every action, human approval for high-risk ones.
          </p>
        </div>
      </div>

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
            {tab === "admin" && isAdmin && <Admin token={session.token} self={session.user} assignable={assignable} />}
          </main>
        </>
      )}
      </div>
    </>
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
        <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
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
        <button className="ghost" onClick={onDone}>Back to sign in</button>
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
        <button className="primary">Create account</button>
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
      setOutcome(await resumeTask(outcome.thread_id, { approved }, session.token));
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
      setOutcome(await resumeTask(outcome.thread_id, { approved: true }, session.token));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // Supplying a missing argument. This is information, not permission: the run
  // continues to the same policy check it would have reached anyway.
  const clarify = async (values: Record<string, string>) => {
    setBusy(true);
    setError("");
    try {
      setOutcome(await resumeTask(outcome.thread_id, { values }, session.token));
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
        <div className="toolbelt">
          <span className="toolbelt-label">Tools your role may call</span>
          <span className="tools">
            {session.tools.map((t) => {
              // Clicking a tool loads the example that uses it, because "these are
              // callable" is easier to show than to say. Tools without an example
              // stay listed, just not clickable.
              const example = EXAMPLES.find((e) => e.tool === t);
              return (
                <button
                  className="tool"
                  key={t}
                  disabled={!example}
                  title={example ? `Try it: ${example.task}` : "a tool this role may call"}
                  onClick={() => example && setTask(example.task)}
                >
                  {t}
                </button>
              );
            })}
          </span>
        </div>
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
      <button className="primary" disabled={!canRun || busy} onClick={run}>
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
          onClarify={clarify}
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
  onClarify,
}: {
  asked: string;
  session: Session;
  agentId: string;
  outcome: any;
  busy: boolean;
  canApprove: boolean;
  onDecide: (approved: boolean) => void;
  onResume: () => void;
  onClarify: (values: Record<string, string>) => void;
}) {
  const held = outcome.status === "approval_required";
  const asking = outcome.status === "clarification_required";
  // A multi-step run carries what each call returned, in order.
  const path: any[] = outcome.observations || [];
  // The tool ran and answered that it could not do the work — an order that does
  // not exist, say. Policy allowed the call, and reporting only "allowed" made a
  // nothing-happened look like a success (reported from a real run).
  const toolSaid: string | undefined = outcome.result?.error;
  const [decided, setDecided] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});

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
      <div className={`status ${outcome.status}${toolSaid ? " reported" : ""}`}>
        {toolSaid
          ? "allowed — but nothing happened"
          : STATUS_LABEL[outcome.status] ?? outcome.status}
      </div>

        <div className="facts resultfacts">
        {outcome.tool && FACT("tool", outcome.tool, "tool")}
        {outcome.approval_id && FACT("approval", outcome.approval_id, "decision")}
        {outcome.thread_id && FACT("thread", outcome.thread_id, "when")}
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
            {asking ? (
              <>
                It chose <code>{outcome.tool}</code> but will not invent the argument
                it needs
              </>
            ) : path.length > 1 ? (
              <>
                It made <b>{path.length} calls</b>, in order:{" "}
                {path.map((o: any) => o.tool).join(" → ")}
              </>
            ) : (
              <>
                It called <code>{outcome.tool}</code>
              </>
            )}
          </li>
        )}
        <li>
          {outcome.status === "error" ? (
            <>The run stopped — {outcome.reason}</>
          ) : asking ? (
            <>
              Paused, waiting for <b>{(outcome.missing || []).join(", ")}</b> — nothing
              has been sent to the tool
            </>
          ) : toolSaid ? (
            <>
              The call was allowed and the tool answered <b>{toolSaid}</b> — nothing
              was done
            </>
          ) : (
            <>
              Policy decided <b>{STATUS_LABEL[outcome.status] ?? outcome.status}</b>
              {outcome.reason && <> — {outcome.reason}</>}
            </>
          )}
        </li>
      </ol>

      <div className="chain" title={agentId}>
        <span className="node agent">agent {shortId(agentId) || "agent"}</span>
        <span className="arrow">→</span>
        <span className="node user">user {session.user}</span>
        {outcome.tool && (
          <>
            <span className="arrow">→</span>
            <span className="node tool">tool {outcome.tool}</span>
          </>
        )}
      </div>

      {held && (
        <div className="approval">
          {decided === "approved" ? (
            <>
              <p className="decided ok">
                <b>Approved by a manager</b> — the agent may perform this action.
              </p>
              {!canApprove && (
                <button className="primary" disabled={busy} onClick={onResume}>
                  Resume now
                </button>
              )}
            </>
          ) : decided === "denied" ? (
            <p className="decided denied">
              <b>Denied by a manager</b> — the agent will not perform this action.
            </p>
          ) : canApprove ? (
            <div className="row">
              <span>
                Held for approval <code>{outcome.approval_id}</code> — you can decide it.
              </span>
              <div>
                <button className="ok" disabled={busy} onClick={() => onDecide(true)}>
                  Approve
                </button>
                <button className="danger" disabled={busy} onClick={() => onDecide(false)}>
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
              <button className="primary" disabled={busy} onClick={onResume}>
                Resume when approved
              </button>
            </div>
          )}
        </div>
      )}

      {asking && (
        <div className="approval clarify">
          <p className="decided">
            The agent needs <b>{(outcome.missing || []).join(", ")}</b> before it can
            call <code>{outcome.tool}</code>. Answering is not approving — the call
            still goes to policy afterwards.
          </p>
          <div className="row fields">
            {(outcome.missing || []).map((field: string) => (
              <label key={field} className="field">
                <span>{field}</span>
                <input
                  value={answers[field] ?? ""}
                  placeholder={field}
                  onChange={(e) => setAnswers({ ...answers, [field]: e.target.value })}
                />
              </label>
            ))}
            <button
              className="primary"
              disabled={busy || (outcome.missing || []).some((f: string) => !answers[f])}
              onClick={() => onClarify(answers)}
            >
              {busy ? "Sending…" : "Send answer"}
            </button>
          </div>
        </div>
      )}

      {!held && outcome.result && Object.keys(outcome.result).length > 0 && (
        <>
          <h3>{toolSaid ? "The tool's answer" : "Result"}</h3>
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
  // A decision is a judgement, and the API records a note with it. Without a field
  // here, "why was this approved?" could only be answered from the reason someone
  // else wrote when the run was held.
  const [notes, setNotes] = useState<Record<string, string>>({});

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
      await decideApproval(id, approved, session.token, notes[id] ?? "");
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
            <span className="node agent">agent {shortId(a.agent || agentId) || "agent"}</span>
            <span className="arrow">→</span>
            <span className="node user">user {a.user}</span>
            <span className="arrow">→</span>
            <span className="node tool">tool {a.tool}</span>
          </div>
          <p className="reason">{a.reason}</p>
          <pre>{JSON.stringify(a.args, null, 2)}</pre>
          <input
            className="notefield"
            placeholder="Add a note — recorded with the decision in the audit trail"
            value={notes[a.id] ?? ""}
            onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })}
            disabled={!canApprove}
          />
          <div className="row">
            <span className="muted">requested by {a.user}</span>
            <div>
              <button className="ok" disabled={!canApprove} onClick={() => decide(a.id, true)}>
                Approve
              </button>
              <button className="danger" disabled={!canApprove} onClick={() => decide(a.id, false)}>
                Deny
              </button>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

function Admin({
  token,
  self,
  assignable,
}: {
  token: string;
  self: string;
  assignable: string[];
}) {
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
    // Disabling your own account is permitted — it was asked for explicitly — but here
    // there is one platform admin, so the way back is not in this UI.
    if (u.enabled && u.username === self) {
      const sure = window.confirm(
        `Disable your own account?\n\n` +
          `You will not be able to sign in again, and nothing in the UI can undo it: ` +
          `re-enabling needs another platform admin, or the operator's Keycloak route. ` +
          `Continue?`,
      );
      if (!sure) return;
    }
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
          assignable={assignable}
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
                {u.username === self && <span className="you">you</span>}
                <br />
                <span className="muted">{u.email}</span>
              </td>
              <td>
                {assignable.map((r) => (
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
              <td>
                <span className={`status ${u.enabled ? "ok" : ""}`}>
                  {u.enabled ? "enabled" : "disabled"}
                </span>
              </td>
              <td className="actions">
                <button onClick={() => toggleEnabled(u)}>{u.enabled ? "Disable" : "Enable"}</button>
                <button onClick={() => reset(u)}>Reset password</button>
                <button className="danger" disabled={u.username === self} onClick={() => remove(u)}>
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

function CreateUser({
  token,
  onCreated,
  assignable,
}: {
  token: string;
  onCreated: () => void;
  assignable: string[];
}) {
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
        {assignable.map((r) => (
          <label key={r} className="role">
            <input type="checkbox" checked={roles.includes(r)} onChange={() => toggle(r)} /> {r}
          </label>
        ))}
      </div>
      <button className="primary">Create</button>
      {error && <div className="error">{error}</div>}
    </form>
  );
}

function Audit({ session }: { session: Session }) {
  const [events, setEvents] = useState<any[]>([]);
  const [stale, setStale] = useState(false);
  // The API matches filters *exactly*, so these are selects rather than search
  // boxes: a substring would silently return nothing. Options come from an
  // unfiltered read — deriving them from a filtered page would hide the values you
  // might want to switch to.
  const [filters, setFilters] = useState<{ event?: string; tool?: string; sub?: string }>({});
  const [options, setOptions] = useState<{ event: string[]; tool: string[]; sub: string[] }>({
    event: [], tool: [], sub: [],
  });
  const filterKey = JSON.stringify(filters);
  useEffect(() => {
    // Keep the last good timeline when a refresh fails, and say it is stale. The
    // previous version caught the failure and set an empty array, so a dropped
    // port-forward or an expired token rendered "No events yet" — which reads as the
    // audit trail having been lost, rather than as not having been re-read.
    const load = async () => {
      try {
        const data = await getAudit(session.token, filters);
        setEvents(data);
        setStale(false);
        if (!filters.event && !filters.tool && !filters.sub) {
          const pick = (k: string): string[] =>
            [...new Set<string>(data.map((e: any) => String(e[k] ?? "")).filter(Boolean))].sort();
          setOptions({ event: pick("event"), tool: pick("tool"), sub: pick("sub") });
        }
      } catch {
        setStale(true);
      }
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
    // re-read when the filters change; the string keeps the effect from looping on a
    // fresh object identity every render
  }, [session.token, filterKey]);

  return (
    <section>
      <h2>Audit timeline</h2>
      <p className="hint">
        One record per event, keyed by identity. Tokens and personal data are
        redacted before anything is written.
        {stale && <> <b className="stale">Not updating — the last good view is below.</b></>}
      </p>
      <div className="filters">
        {(["event", "tool", "sub"] as const).map((k) => (
          <label key={k}>
            <span>{k === "sub" ? "user" : k}</span>
            <select
              value={filters[k] ?? ""}
              onChange={(e) => setFilters({ ...filters, [k]: e.target.value || undefined })}
            >
              <option value="">any</option>
              {options[k].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>
        ))}
        {(filters.event || filters.tool || filters.sub) && (
          <button className="ghost" onClick={() => setFilters({})}>Clear</button>
        )}
        <span className="muted">{events.length} shown</span>
      </div>
      <div className="timeline">
        {events.map((e, i) => (
          <div className="event" key={i}>
            <code className={`ev ${tone(e.event)}`}>{e.event}</code>
            <span className="facts">
              {e.spiffe_id && FACT("agent", shortId(e.spiffe_id), "agent")}
              {e.sub && FACT("user", e.sub, "user")}
              {e.tool && FACT("tool", e.tool, "tool")}
              {e.decision && FACT("decision", e.decision, "decision")}
              {e.ts && FACT("when", at(e.ts), "when")}
              {e.policy_version && FACT("policy", e.policy_version, "policy")}
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
            <code className={`ev ${tone(outcome(a))}`}>{outcome(a)}</code>
            <span className="facts">
              {FACT("user", a.user, "user")}
              {FACT("tool", a.tool, "tool")}
              {FACT("when", at(a.at), "when")}
              {a.policy_version && FACT("policy", a.policy_version, "policy")}
            </span>
            {a.reason && <p className="reason">{a.reason}</p>}
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
            <span className="facts">
              {a.args?.customer_id && FACT("customer", a.args.customer_id, "tool")}
              {FACT("asked by", a.user, "user")}
              {FACT("when", at(a.created_at), "when")}
              {a.approver && FACT("decided by", a.approver, "decision")}
            </span>
            {a.reason && <p className="reason">{a.reason}</p>}
            {a.note && <p className="reason">“{a.note}”</p>}
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
