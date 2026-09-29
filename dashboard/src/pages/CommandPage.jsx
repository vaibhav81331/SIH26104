import { useCallback, useEffect, useState } from "react";
import { useApp, useData } from "../lib/state.jsx";
import { api } from "../lib/api.js";
import { BandChip, Loading, Seg } from "../components/ui.jsx";
import { fmt } from "../lib/bands.js";

const MUNICIPAL = {
  Watch: ["Alert ward officers and ASHA workers", "Check water kiosks and public taps", "Pre-position ORS at health centres"],
  Warning: ["Open cooling centres in priority wards", "Run water tankers to slums and markets", "Advise construction sites to shift working hours"],
  Emergency: ["Open all cooling centres, extend hours into the night", "Enforce the 11 am–4 pm outdoor work restriction", "Door-to-door checks on elderly people living alone"],
};

function Checklist({ alert }) {
  const { bump } = useApp();
  const [msg, setMsg] = useState(null);
  const done = new Set((alert.acks ?? []).map((a) => a.action));
  const ack = async (action) => {
    try {
      await api.post("/hap/ack", { alertId: alert.alertId, action, by: "dashboard" });
      bump();
    } catch (e) {
      setMsg(e.message);
    }
  };
  return (
    <div>
      {(MUNICIPAL[alert.band] ?? []).map((a) => (
        <label key={a} className="row small" style={{ margin: "4px 0" }}>
          <input type="checkbox" checked={done.has(a)} onChange={() => !done.has(a) && ack(a)} disabled={done.has(a)} />
          {a}
        </label>
      ))}
      {msg && <div className="small" role="alert">{msg}</div>}
    </div>
  );
}

function Subscriptions() {
  const { meta, bump } = useApp();
  const [subs, setSubs] = useState(null);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({ name: "", channel: "sms", address: "", language: "or", audience: "public", cities: "Bhubaneswar", minLevel: 2 });
  const load = useCallback(() => api.getAuth("/subscriptions").then(setSubs).catch((e) => setErr(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const add = async (e) => {
    e.preventDefault();
    try {
      await api.post("/subscribe", { ...form, minLevel: Number(form.minLevel), cities: form.cities ? [form.cities] : [] });
      setForm({ ...form, name: "", address: "" });
      load();
      bump();
    } catch (x) {
      setErr(x.message);
    }
  };
  const remove = async (id) => {
    await api.del(`/subscriptions/${id}`).catch((x) => setErr(x.message));
    load();
  };

  return (
    <div className="card">
      <h2>Subscribers</h2>
      <p className="small muted">Officials, facilities and community volunteers receive the advisory for their area, audience and language. In simulated mode nothing leaves this machine.</p>
      <form className="grid three" onSubmit={add} style={{ alignItems: "end" }}>
        <label className="field">Name<input type="text" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="field">Channel
          <select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>{meta?.channels.map((c) => <option key={c}>{c}</option>)}</select>
        </label>
        <label className="field">{form.channel === "webhook" ? "URL" : "Phone / address"}<input type="text" required value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder={form.channel === "webhook" ? "https://…" : "+91…"} /></label>
        <label className="field">City
          <select value={form.cities} onChange={(e) => setForm({ ...form, cities: e.target.value })}>
            {["Bhubaneswar", "Cuttack", "Berhampur", "Sambalpur", "Rourkela", "Puri", "Balasore", "Balangir"].map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="field">Language
          <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}><option value="or">Odia</option><option value="hi">Hindi</option><option value="en">English</option></select>
        </label>
        <label className="field">Audience
          <select value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value })}>{meta?.audiences.map((a) => <option key={a} value={a}>{a.replace("_", " ")}</option>)}</select>
        </label>
        <label className="field">From level
          <select value={form.minLevel} onChange={(e) => setForm({ ...form, minLevel: e.target.value })}><option value={1}>Watch</option><option value={2}>Warning</option><option value={3}>Emergency</option></select>
        </label>
        <button className="btn primary" type="submit">Add subscriber</button>
      </form>
      {err && <div className="small" role="alert" style={{ marginTop: 8 }}>{err}</div>}
      {subs?.length > 0 && (
        <table className="data" style={{ marginTop: 12 }}>
          <thead><tr><th>Name</th><th>Channel</th><th>Address</th><th>Area</th><th>Lang / audience</th><th /></tr></thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td><td>{s.channel}</td><td>{s.address}</td>
                <td>{[...(s.cities ?? []), ...(s.wards ?? [])].join(", ")}</td>
                <td>{s.language} · {s.audience}</td>
                <td><button className="btn sm" onClick={() => remove(s.id)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Deliveries({ refreshKey }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let alive = true;
    api.getAuth("/deliveries?limit=50").then((r) => alive && setRows(r)).catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [refreshKey]);
  if (!rows) return <Loading />;
  if (!rows.length) return <div className="muted small">Nothing sent yet. Add a subscriber, then “Evaluate & dispatch”.</div>;
  return (
    <div className="table-wrap" style={{ maxHeight: 320 }}>
      <table className="data">
        <thead><tr><th>When</th><th>To</th><th>Place</th><th>Level</th><th>Status</th><th>Message</th></tr></thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.id}>
              <td className="small">{new Date(d.at).toLocaleTimeString()}</td>
              <td className="small">{d.subscriber}<div className="muted">{d.channel} {d.to}</div></td>
              <td className="small">{d.place}</td>
              <td><BandChip band={d.level} /></td>
              <td className="small">{d.status}</td>
              <td className="small" style={{ maxWidth: 380 }}>{d.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CommandPage() {
  const { events, version, bump } = useApp();
  const [scope, setScope] = useState("ward");
  const [sel, setSel] = useState(null);
  const [dispatchMsg, setDispatchMsg] = useState(null);
  const active = useData(`/alerts/active?scope=${scope}`, [scope]);
  const history = useData("/alerts/history?limit=60");
  const audit = useData("/audit?limit=30");

  const dispatch = async () => {
    try {
      const r = await api.post("/alerts/evaluate", {});
      setDispatchMsg(`${r.dispatched.length} message(s) dispatched for ${r.active} active alerts.`);
      bump();
    } catch (e) {
      setDispatchMsg(e.message);
    }
  };

  const selected = active.data?.alerts.find((a) => a.key === sel) ?? active.data?.alerts[0];

  return (
    <div className="page">
      <h1>Command</h1>
      <p className="lede">Heat Action Plan status for every ward and district, the evidence behind each level, and the actions and messages it triggers. Levels escalate on the forecast and de-escalate only after the heat has clearly passed.</p>

      <div className="row" style={{ marginBottom: 12 }}>
        <Seg label="Scope" value={scope} onChange={setScope} options={[["ward", "Wards"], ["district", "Districts"]]} />
        {active.data && Object.entries(active.data.counts).map(([b, n]) => <BandChip key={b} band={b} suffix={<span className="muted"> {n}</span>} />)}
        <div className="spacer" />
        <button className="btn primary" onClick={dispatch}>Evaluate &amp; dispatch</button>
      </div>
      {dispatchMsg && <div className="sentence" role="status">{dispatchMsg}</div>}

      <div className="grid two">
        <div className="card">
          <h2>Active alerts {active.data && <span className="muted small">as of {active.data.asOf}</span>}</h2>
          {!active.data ? <Loading /> : active.data.alerts.length === 0 ? <div className="muted">No active alerts.</div> : (
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Place</th><th>Level</th><th>Since</th><th className="num">HTSI today</th><th className="num">Peak D+1–3</th><th className="num">MRI</th></tr></thead>
                <tbody>
                  {active.data.alerts.map((a) => (
                    <tr key={a.key} className={`click${selected?.key === a.key ? " sel" : ""}`} onClick={() => setSel(a.key)}>
                      <td>{a.name}<div className="muted small">{a.city ?? ""}</div></td>
                      <td><BandChip band={a.band} /></td>
                      <td className="small">{a.since}</td>
                      <td className="num">{fmt(a.today?.htsi, 0)}</td>
                      <td className="num">{fmt(Math.max(...a.forecast.slice(0, 3).map((f) => f.htsi ?? 0)), 0)}</td>
                      <td className="num">{fmt(a.today?.mri, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <h2>{selected ? selected.name : "Select an alert"}</h2>
          {selected && (
            <div className="stack">
              <div className="row"><BandChip band={selected.band} large /><span className="small muted">since {selected.since}</span></div>
              <div className="sentence">{selected.target?.reason}</div>
              {selected.lastTransition && <div className="small muted">Last change {selected.lastTransition.date}: {selected.lastTransition.from} → {selected.lastTransition.to} ({selected.lastTransition.kind})</div>}
              <h3>Heat Action Plan checklist</h3>
              <Checklist alert={selected} key={`${selected.alertId}-${version}`} />
              <div className="row">
                <a className="btn" href={`/v1/alerts/${selected.alertId}/cap.xml`} target="_blank" rel="noreferrer">CAP 1.2 XML</a>
                <a className="btn" href={`/v1/advisory/${selected.id}?lang=or`} target="_blank" rel="noreferrer">Odia advisory (JSON)</a>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        <div className="card">
          <h2>Level changes</h2>
          {!history.data ? <Loading /> : (
            <div className="feed">
              {history.data.transitions.map((t, i) => (
                <div key={i}><b>{t.date}</b> · {t.name}: {t.from} → <b>{t.to}</b> <span className="muted">— {t.reason}</span></div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <h2>Live feed & audit</h2>
          <div className="feed">
            {events.map((e, i) => (
              <div key={`e${i}`}><span className="muted">{e.at}</span> <b>{e.type}</b> {e.type === "transitions" ? `${e.data.length} level change(s)` : e.type === "asof" ? `clock → ${e.data.asOf}` : e.type === "deliveries" ? `${e.data.length} message(s)` : e.data.level ?? ""}</div>
            ))}
            {audit.data?.map((a) => (
              <div key={a.id}><span className="muted">{new Date(a.at).toLocaleTimeString()}</span> {a.type}{a.level ? ` · ${a.level}` : ""}{a.placeId ? ` · ${a.scope} ${a.placeId}` : ""}{a.asOf ? ` · as of ${a.asOf}` : ""}</div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 14 }}><Subscriptions /></div>
      <div className="card" style={{ marginTop: 14 }}>
        <h2>Delivery log</h2>
        <Deliveries refreshKey={version} />
      </div>
    </div>
  );
}
