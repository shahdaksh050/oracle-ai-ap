import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

const labels = {
  received: "Received",
  extracted: "Extracted",
  validated: "Validated",
  ready: "Ready to submit",
  review: "Needs review",
  batch_finance: "Batch finance approval",
  batch_executive: "Batch executive approval",
  pending: "Finance approval",
  executive: "Executive approval",
  queued: "Queued",
  dismissed: "Dismissed",
};
const sections = {
  invoices: "Invoice inbox",
  queue: "Payment queue",
  operations: "Operations",
  adapters: "Supplier adapters",
  context: "Search results",
};
const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
const amount = (v) => (v == null ? "—" : inr.format(v));
const stamp = (v) =>
  new Date(v).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
const fieldNames = {
  number: "Invoice number",
  date: "Invoice date",
  supplier: "Supplier GSTIN",
  buyer: "Buyer GSTIN",
  place: "Place of supply code",
  currency: "Currency",
  supply: "Supply type",
  reverse_charge: "Reverse charge",
  taxable: "Taxable value",
  cgst: "CGST",
  sgst: "SGST",
  igst: "IGST",
  total: "Invoice total",
};
const lineKeys = ["po", "sku", "hsn", "qty", "unit_price", "gst_rate"];
const lineNames = [
  "Purchase order",
  "Item",
  "HSN",
  "Quantity",
  "Unit price",
  "GST rate (%)",
];
const emptyLine = () => Object.fromEntries(lineKeys.map((k) => [k, ""]));
async function api(path, method = "GET", body) {
  const opt = { method, credentials: "same-origin" };
  if (body instanceof FormData) opt.body = body;
  else if (body) {
    opt.body = JSON.stringify(body);
    opt.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch("/api" + path, opt);
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    const d = e.detail;
    throw Error(
      typeof d === "string"
        ? d
        : Array.isArray(d)
          ? d.map((x) => x.loc.slice(1).join(".") + " " + x.msg).join(" · ")
          : "Request failed (" + r.status + ")",
    );
  }
  return r.json();
}
function Brand() {
  return (
    <div className="brand">
      <span className="mark" aria-hidden="true">
        O
      </span>
      <span>
        Oracle <small>WORKSPACE</small>
      </span>
    </div>
  );
}
function Badge({ stage }) {
  return <span className={"badge " + stage}>{labels[stage] || stage}</span>;
}
function SignIn({ done }) {
  const [token, set] = useState(""),
    [error, fail] = useState("");
  return (
    <main className="login">
      <Brand />
      <div className="login-card">
        <p className="kicker">ACCOUNTS PAYABLE</p>
        <h1>Workspace sign-in</h1>
        <p>Enter your assigned access key to open your finance workspace.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/session", "POST", { token });
              await done();
            } catch (err) {
              fail(err.message);
            }
          }}
        >
          <label>
            Access key
            <input
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(e) => set(e.target.value)}
              required
            />
          </label>
          <button className="primary">Sign in</button>
        </form>
        {error && <p role="alert">{error}</p>}
      </div>
    </main>
  );
}
function Correction({ doc, onSave, cancel }) {
  const [f, set] = useState(() => ({
    ...Object.fromEntries(Object.keys(fieldNames).map((k) => [k, ""])),
    ...doc.fields,
    lines: doc.fields.lines?.length ? doc.fields.lines : [emptyLine()],
  }));
  const [reason, why] = useState(""),
    [page, at] = useState(1);
  const field = (k, v) => set({ ...f, [k]: v });
  return (
    <form
      className="panel"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({ fields: f, reason, page: Number(page), version: doc.version });
      }}
    >
      <h3>Review source fields</h3>
      <div className="field-grid">
        {Object.entries(fieldNames).map(([k, n]) => (
          <label key={k}>
            {n}
            <input
              value={f[k] ?? ""}
              required
              onChange={(e) => field(k, e.target.value)}
            />
          </label>
        ))}
      </div>
      {f.lines.map((line, i) => (
        <fieldset key={i}>
          <legend>Line {i + 1}</legend>
          <div className="field-grid">
            {lineKeys.map((k, j) => (
              <label key={k}>
                {lineNames[j]}
                <input
                  value={line[k] ?? ""}
                  required
                  onChange={(e) =>
                    field(
                      "lines",
                      f.lines.map((r, n) =>
                        i === n ? { ...r, [k]: e.target.value } : r,
                      ),
                    )
                  }
                />
              </label>
            ))}
          </div>
          {f.lines.length > 1 && (
            <button
              type="button"
              onClick={() =>
                field(
                  "lines",
                  f.lines.filter((_, n) => n !== i),
                )
              }
            >
              Remove line
            </button>
          )}
        </fieldset>
      ))}
      <button
        type="button"
        onClick={() => field("lines", [...f.lines, emptyLine()])}
      >
        Add line
      </button>
      <label>
        Evidence page
        <input
          type="number"
          min="1"
          max="12"
          required
          value={page}
          onChange={(e) => at(e.target.value)}
        />
      </label>
      <label>
        Review reason
        <input
          required
          minLength="3"
          maxLength="500"
          value={reason}
          onChange={(e) => why(e.target.value)}
        />
      </label>
      <div className="actions">
        <button className="primary">Save review</button>
        <button type="button" onClick={cancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
function Detail({ doc, me, action, back }) {
  const [edit, setEdit] = useState(false),
    [why, reason] = useState(""),
    [closing, close] = useState(false);
  const base = "/workflows/" + doc.id,
    mutate = (suffix, data, method = "POST") =>
      action(() => api(base + suffix, method, data), doc.id);
  const source = "/api" + base + "/source";
  const clerk = me.role === "clerk";
  const open = [
    "ready",
    "review",
    "pending",
    "executive",
    "batch_finance",
    "batch_executive",
  ].includes(doc.stage);
  const panels = {
    source: (
      <section className="panel">
        <div className="row">
          <h3>Source document</h3>
          <a href={source} target="_blank" rel="noreferrer">
            Open original ↗
          </a>
        </div>
        <object data={source} className="preview" aria-label="Source document">
          <a href={source}>View the invoice</a>
        </object>
      </section>
    ),
    fields: (
      <section className="panel">
        <h3>Extracted fields</h3>
        <dl>
          {Object.entries(fieldNames).map(([k, n]) => (
            <div key={k}>
              <dt>{n}</dt>
              <dd>
                {doc.fields[k] || "—"}{" "}
                {doc.evidence[k] && (
                  <a
                    title={doc.evidence[k].quote}
                    href={source + "#page=" + doc.evidence[k].page}
                    target="_blank"
                    rel="noreferrer"
                  >
                    p.{doc.evidence[k].page}
                  </a>
                )}
              </dd>
            </div>
          ))}
        </dl>
        <h4>Invoice lines</h4>
        {doc.fields.lines?.map((l, i) => (
          <p key={i}>
            {l.po} · {l.sku} · HSN {l.hsn} · {l.qty} × {amount(l.unit_price)} ·
            GST {l.gst_rate}%{" "}
            {doc.evidence["lines." + i] && (
              <a
                href={source + "#page=" + doc.evidence["lines." + i].page}
                target="_blank"
                rel="noreferrer"
              >
                p.{doc.evidence["lines." + i].page}
              </a>
            )}
          </p>
        ))}
      </section>
    ),
    matches: (
      <section className="panel">
        <h3>Goods receipt matches</h3>
        {doc.matches.length ? (
          doc.matches.map((m, i) => (
            <p key={i}>
              {m.grn} · {m.po} · {m.sku} <b>{m.qty} units</b>
            </p>
          ))
        ) : (
          <p>No matched quantities.</p>
        )}
      </section>
    ),
    history: (
      <section className="panel">
        <h3>Audit history</h3>
        {doc.events.map((ev, i) => (
          <details key={i}>
            <summary>
              {ev.kind} · {ev.actor} · {stamp(ev.created)}
            </summary>
            <pre>{JSON.stringify(ev.details, null, 2)}</pre>
          </details>
        ))}
      </section>
    ),
  };
  return (
    <>
      <button className="back" onClick={back}>
        ← Invoice inbox
      </button>
      <div className="row">
        <div>
          <p className="kicker">INVOICE REVIEW · VERSION {doc.version}</p>
          <h1>{doc.fields.number || "Unidentified invoice"}</h1>
        </div>
        <Badge stage={doc.stage} />
      </div>
      {doc.batch && (
        <section className="panel">
          <h3>Approval batch · {amount(doc.batch.amount_exact ?? doc.batch.amount)}</h3>
          {doc.batch.items.map((member) => (
            <p key={member.id}>
              {member.number} ? {member.supplier} ? version {member.version} ?{" "}
              {amount(member.total)}
            </p>
          ))}
          {doc.batch.status === "pending" &&
            me.queue_enabled &&
            (me.role === "executive" ||
              (me.role === "finance" && doc.stage === "batch_finance")) && (
              <button
                className="primary"
                onClick={() =>
                  action(
                    () =>
                      api("/batches/" + doc.batch.id + "/approve", "POST", {}),
                    doc.id,
                  )
                }
              >
                Approve entire batch
              </button>
            )}
        </section>
      )}
      {doc.issues.length > 0 && (
        <div className="notice">
          <strong>Review required</strong>
          <ul>
            {doc.issues.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="actions">
        {clerk && open && (
          <button onClick={() => setEdit(!edit)}>Review fields</button>
        )}
        {clerk && doc.stage === "ready" && (
          <button
            className="primary"
            onClick={() => mutate("/submit", { version: doc.version })}
          >
            Submit for approval
          </button>
        )}
        {clerk &&
          ["received", "extracted", "validated"].includes(doc.stage) && (
            <button onClick={() => mutate("/resume", {})}>
              Resume processing
            </button>
          )}
        {((me.role === "executive" &&
          ["pending", "executive"].includes(doc.stage)) ||
          (me.role === "finance" && doc.stage === "pending")) && (
          <button
            disabled={!me.queue_enabled}
            className="primary"
            onClick={() => mutate("/approve", { version: doc.version })}
          >
            Approve and queue {amount(doc.fields.total)}
          </button>
        )}
        {clerk && open && (
          <button onClick={() => close(!closing)}>Dismiss proposal</button>
        )}
      </div>
      {closing && (
        <form
          className="panel"
          onSubmit={(e) => {
            e.preventDefault();
            mutate("/dismiss", { version: doc.version, reason: why });
          }}
        >
          <label>
            Reason for dismissal
            <input
              minLength="3"
              required
              value={why}
              onChange={(e) => reason(e.target.value)}
            />
          </label>
          <button>Confirm dismissal</button>
        </form>
      )}
      {edit && (
        <Correction
          doc={doc}
          cancel={() => setEdit(false)}
          onSave={async (data) => {
            if (await mutate("/fields", data, "PUT")) setEdit(false);
          }}
        />
      )}
      <div className="detail-grid">
        {doc.components.map(
          (k) =>
            panels[k] && <React.Fragment key={k}>{panels[k]}</React.Fragment>,
        )}
      </div>
    </>
  );
}
function Adapters({ rows, me, run }) {
  const [label, setLabel] = useState(""),
    [target, setTarget] = useState("number");
  return (
    <>
      {["qa", "clerk"].includes(me.role) && (
        <form
          className="panel inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            run(() =>
              api("/adapters", "POST", { aliases: { [label]: target } }),
            );
          }}
        >
          <label>
            Supplier field label
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              required
              placeholder="bill no"
            />
          </label>
          <label>
            Invoice field
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {Object.entries(fieldNames).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <button>Stage adapter</button>
        </form>
      )}
      {rows.map((r) => (
        <article className="panel" key={r.id}>
          <strong>
            {Object.entries(r.aliases)
              .map(([a, b]) => a + " → " + b)
              .join(", ")}
          </strong>
          <p>
            {r.status} · {r.report.sandbox}
          </p>
          {me.role === "qa" && r.status === "staged" && (
            <button
              onClick={() =>
                run(() => api("/adapters/" + r.id + "/release", "POST", {}))
              }
            >
              Release adapter
            </button>
          )}
        </article>
      ))}
      {!rows.length && <p className="empty">No supplier adapters staged.</p>}
    </>
  );
}
function Workspace({ me, logout }) {
  const [selected, select] = useState([]);
  const [tab, nav] = useState("invoices"),
    [filter, filterBy] = useState("all"),
    [rows, setRows] = useState([]),
    [ops, metrics] = useState(null),
    [doc, detail] = useState(null),
    [q, query] = useState(""),
    [err, fail] = useState(""),
    [busy, wait] = useState(false);
  async function load(name, search) {
    let path = {
      invoices: "/workflows",
      queue: "/queue",
      adapters: "/adapters",
      context: "/context?q=" + encodeURIComponent(search || ""),
    }[name];
    if (name === "operations") metrics(await api("/operations"));
    else setRows(await api(path));
  }
  async function show(name, search) {
    select([]);
    fail("");
    detail(null);
    nav(name);
    setRows([]);
    try {
      await load(name, search);
    } catch (e) {
      fail(e.message);
    }
  }
  async function inspect(id) {
    try {
      fail("");
      detail(await api("/workflows/" + id));
    } catch (e) {
      fail(e.message);
    }
  }
  useEffect(() => {
    const id = new URLSearchParams(location.search).get("workflow");
    if (id) inspect(id);
    else show("invoices");
  }, []);
  async function run(fn, id) {
    if (busy) return false;
    wait(true);
    fail("");
    try {
      const result = await fn();
      if (id || result?.document_id) await inspect(id || result.id);
      else await load(tab, q);
      return true;
    } catch (e) {
      fail(e.message);
      return false;
    } finally {
      wait(false);
    }
  }
  const subset =
    tab === "invoices"
      ? rows.filter(
          (r) =>
            filter === "all" ||
            r.stage === filter ||
            (filter === "approvals" &&
              [
                "pending",
                "executive",
                "batch_finance",
                "batch_executive",
              ].includes(r.stage)),
        )
      : rows;
  const go = (name) => {
    filterBy("all");
    show(name);
  };
  return (
    <div className="shell">
      <aside>
        <Brand />
        <div className="nav-head">ACCOUNTS PAYABLE</div>
        <nav>
          {Object.entries(sections)
            .filter(([k]) => k !== "context")
            .map(([k, v]) => (
              <button
                key={k}
                className={tab === k ? "active" : ""}
                onClick={() => go(k)}
              >
                {v}
              </button>
            ))}
        </nav>
        <div className="profile">
          <b>{me.tenant}</b>
          <small>{me.role} workspace</small>
          <button onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="workspace">
        <header>
          <span>Finance workspace</span>
          <span className="mode">
            <i />
            {me.queue_enabled ? "Internal queue enabled" : "Shadow mode"}
          </span>
        </header>
        <div className="body">
          <form
            className="search"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const spec = await api("/view?q=" + encodeURIComponent(q));
                filterBy(spec.filter || "all");
                await show(spec.component, spec.query);
              } catch (e) {
                fail(e.message);
              }
            }}
          >
            <input
              aria-label="Search workspace"
              placeholder="Search invoices or ask for approvals…"
              value={q}
              required
              maxLength="200"
              onChange={(e) => query(e.target.value)}
            />
            <button>Search</button>
          </form>
          {err && (
            <p className="notice" role="alert">
              {err}
            </p>
          )}
          <fieldset disabled={busy} className="content">
            {doc ? (
              <Detail
                key={doc.id + "-" + doc.version + "-" + doc.stage}
                doc={doc}
                me={me}
                action={run}
                back={() => go("invoices")}
              />
            ) : (
              <>
                <div className="row heading">
                  <div>
                    <p className="kicker">
                      {me.tenant.toUpperCase()} · FINANCE
                    </p>
                    <h1>{sections[tab]}</h1>
                  </div>
                  {tab === "invoices" && me.role === "clerk" && (
                    <label className="primary upload">
                      Upload invoice
                      <input
                        type="file"
                        accept=".pdf,.jpeg,.jpg,.png"
                        onChange={(e) => {
                          const file = e.target.files[0];
                          if (file) {
                            const data = new FormData();
                            data.append("file", file);
                            run(() => api("/workflows", "POST", data));
                            e.target.value = "";
                          }
                        }}
                      />
                    </label>
                  )}
                </div>
                {tab === "invoices" && (
                  <div className="filters">
                    {[
                      ["all", "All invoices"],
                      ["review", "Exceptions"],
                      ["approvals", "Awaiting approval"],
                    ].map(([k, v]) => (
                      <button
                        className={filter === k ? "chosen" : ""}
                        key={k}
                        onClick={() => filterBy(k)}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                )}
                {tab === "invoices" && selected.length >= 2 && (
                  <button
                    className="primary"
                    onClick={async () => {
                      const ok = await run(() =>
                        api("/batches", "POST", { items: selected }),
                      );
                      if (ok) select([]);
                    }}
                  >
                    Submit {selected.length} invoices as one batch
                  </button>
                )}
                {tab === "invoices" && (
                  <div className="tablewrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Invoice</th>
                          <th>Supplier GSTIN</th>
                          <th>Amount</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {subset.map((r) => (
                          <tr key={r.id}>
                            <td>
                              {me.role === "clerk" && r.stage === "ready" && (
                                <input
                                  type="checkbox"
                                  aria-label={
                                    "Select " + r.number + " for batch"
                                  }
                                  checked={selected.some((x) => x.id === r.id)}
                                  onChange={(e) =>
                                    select(
                                      e.target.checked
                                        ? [
                                            ...selected,
                                            { id: r.id, version: r.version },
                                          ]
                                        : selected.filter((x) => x.id !== r.id),
                                    )
                                  }
                                />
                              )}{" "}
                              <button
                                className="link"
                                onClick={() => inspect(r.id)}
                              >
                                {r.number || r.filename}
                              </button>
                            </td>
                            <td>{r.supplier || "—"}</td>
                            <td>{amount(r.amount)}</td>
                            <td>
                              <Badge stage={r.stage} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!subset.length && (
                      <p className="empty">No invoices in this view.</p>
                    )}
                  </div>
                )}
                {tab === "queue" && (
                  <div className="tablewrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Approved invoice</th>
                          <th>Amount</th>
                          <th>Approver</th>
                          <th>Queued</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr key={r.workflow_id}>
                            <td>
                              <button
                                className="link"
                                onClick={() => inspect(r.workflow_id)}
                              >
                                {r.business_key}
                              </button>
                            </td>
                            <td>{amount(r.amount_exact ?? r.amount)}</td>
                            <td>{r.approver}</td>
                            <td>{stamp(r.created)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!rows.length && (
                      <p className="empty">No approved payment proposals.</p>
                    )}
                  </div>
                )}
                {tab === "context" && (
                  <div className="panel">
                    {rows.map((r) => (
                      <p key={r.id}>
                        <button className="link" onClick={() => inspect(r.id)}>
                          {r.summary || r.id}
                        </button>{" "}
                        <Badge stage={r.stage} />
                      </p>
                    ))}
                    {!rows.length && <p>No matching history.</p>}
                  </div>
                )}
                {tab === "operations" && ops && (
                  <>
                    <div className="cards">
                      {[
                        ["Invoices", ops.invoices],
                        ["Pending notifications", ops.notifications.pending],
                        ["Delivery failures", ops.notifications.failures],
                        [
                          "Oldest open (hours)",
                          Math.floor(ops.oldest_open_seconds / 3600),
                        ],
                      ].map(([k, v]) => (
                        <div className="panel" key={k}>
                          <small>{k}</small>
                          <strong>{v}</strong>
                        </div>
                      ))}
                    </div>
                    <section className="panel">
                      <h3>Worker latency</h3>
                      {ops.timings.map((t) => (
                        <p key={t.pod}>
                          {t.pod} ? p95 {t.p95_ms} ms ? {t.runs} runs
                        </p>
                      ))}
                      <h3>Workflow status</h3>
                      {ops.stages.map((r) => (
                        <p key={r.stage}>
                          <Badge stage={r.stage} /> {r.count}
                        </p>
                      ))}
                    </section>
                  </>
                )}
                {tab === "adapters" && (
                  <Adapters rows={rows} me={me} run={run} />
                )}
              </>
            )}
          </fieldset>
          {busy && <p role="status">Processing…</p>}
        </div>
      </main>
    </div>
  );
}
function App() {
  const [me, who] = useState(null),
    [ready, setReady] = useState(false);
  async function load() {
    try {
      who(await api("/me"));
    } catch {
      who(null);
    } finally {
      setReady(true);
    }
  }
  useEffect(() => {
    load();
  }, []);
  if (!ready) return null;
  return me ? (
    <Workspace
      me={me}
      logout={async () => {
        await api("/session", "DELETE");
        who(null);
      }}
    />
  ) : (
    <SignIn done={load} />
  );
}
createRoot(document.getElementById("root")).render(<App />);
