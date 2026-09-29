import { useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { AppProvider, useApp } from "./lib/state.jsx";
import { getApiKey, setApiKey } from "./lib/api.js";
import MapPage from "./pages/MapPage.jsx";
import CommandPage from "./pages/CommandPage.jsx";
import ValidationPage from "./pages/ValidationPage.jsx";
import CoolingPage from "./pages/CoolingPage.jsx";
import FieldPage from "./pages/FieldPage.jsx";

function Clock() {
  const { clock, setAsOf, step, togglePlay, playing, refreshLive } = useApp();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (!clock) return null;
  const live = clock.mode === "live";
  const run = (fn) => async () => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="clock" role="group" aria-label="Forecast issuance date">
      <span className={`mode ${live ? "live" : "replay"}`}>{live ? "Live" : "Replay"}</span>
      <button className="btn sm" onClick={run(() => step(-1))} disabled={busy || live} aria-label="Previous day">◀</button>
      <select value={live ? "" : clock.asOf} onChange={(e) => run(() => setAsOf(e.target.value))()} disabled={busy} aria-label="As-of date">
        {live && <option value="">Live · {clock.asOf}</option>}
        {clock.dates.map((d) => (
          <option key={d} value={d}>
            As of {d}
          </option>
        ))}
      </select>
      <button className="btn sm" onClick={run(() => step(1))} disabled={busy || live} aria-label="Next day">▶</button>
      <button className="btn sm" onClick={togglePlay} disabled={live} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button>
      <button className="btn sm" onClick={run(refreshLive)} disabled={busy} title="Fetch today's numerical weather forecast and run it through the same pipeline">
        {busy ? "…" : "Go live"}
      </button>
      {err && <span className="small" style={{ color: "var(--band-emergency)" }} role="alert">{err}</span>}
    </div>
  );
}

function KeyButton() {
  const [open, setOpen] = useState(false);
  const [v, setV] = useState(getApiKey());
  return (
    <span style={{ position: "relative" }}>
      <button className="btn sm" onClick={() => setOpen(!open)} aria-expanded={open}>Operator key</button>
      {open && (
        <div className="card" style={{ position: "absolute", right: 0, top: 36, zIndex: 1000, width: 280 }}>
          <label className="field">
            API key for sending alerts and triggering actions
            <input type="password" value={v} onChange={(e) => setV(e.target.value)} />
          </label>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn sm primary" onClick={() => { setApiKey(v); setOpen(false); }}>Save</button>
            <span className="small muted">Stored in this browser only.</span>
          </div>
        </div>
      )}
    </span>
  );
}

function Shell() {
  const { meta, error, clock } = useApp();
  const loc = useLocation();
  if (loc.pathname.startsWith("/field")) return <FieldPage />;
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <img src="/icon.svg" alt="" />
          <span>USHMA <small>Heat-health early warning · Odisha</small></span>
        </div>
        <nav className="nav" aria-label="Sections">
          <NavLink to="/" end>Map</NavLink>
          <NavLink to="/command">Command</NavLink>
          <NavLink to="/cooling">Cooling centres</NavLink>
          <NavLink to="/validation">Evidence</NavLink>
          <NavLink to="/field">Field view</NavLink>
        </nav>
        <div className="spacer" />
        <Clock />
        <KeyButton />
      </header>
      <div className="notice" role="note">
        {error ? (
          <span style={{ color: "var(--band-emergency)" }}>Cannot reach the USHMA API ({error}). Start it with <code>npm start</code> in <code>server/</code>.</span>
        ) : clock?.mode === "live" ? (
          <span><b>Live</b>: built from today's Open-Meteo forecast through the same index, model and risk code as the replay. Alerts issued in live mode are CAP status <i>Actual</i>.</span>
        ) : (
          <span><b>Historical replay</b> of the {meta?.replay?.start}–{meta?.replay?.end} heat season. Every forecast shown was made by a model that never saw 2024. Alerts are CAP status <i>Exercise</i>.</span>
        )}
        {meta?.syntheticWards && <span>· <b>Ward boundaries are synthetic</b> until real ward files are supplied.</span>}
        <span>· Heat–mortality curve is literature-transferred; see Evidence.</span>
      </div>
      <main>
        <Routes>
          <Route path="/" element={<MapPage />} />
          <Route path="/command" element={<CommandPage />} />
          <Route path="/cooling" element={<CoolingPage />} />
          <Route path="/validation" element={<ValidationPage />} />
          <Route path="*" element={<div className="page"><h1>Not found</h1></div>} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
