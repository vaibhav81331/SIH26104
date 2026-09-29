import { useState } from "react";
import { useApp, useData } from "../lib/state.jsx";
import { api } from "../lib/api.js";
import { BandChip, Seg, Stat, Loading } from "./ui.jsx";
import ForecastChart from "./ForecastChart.jsx";
import { fmt, fmtInt } from "../lib/bands.js";

const LANGS = [["en", "English"], ["hi", "हिन्दी"], ["or", "ଓଡ଼ିଆ"]];

function DaysTable({ days }) {
  return (
    <div className="table-wrap" style={{ maxHeight: "none" }}>
      <table className="data">
        <thead>
          <tr>
            <th>Day</th><th>Band</th><th className="num">HTSI (80%)</th><th className="num">P(Warning+)</th><th className="num">MRI</th><th className="num">Excess deaths</th>
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.date}>
              <td>{d.lead === 0 ? "Today" : `D+${d.lead}`}<div className="muted small">{d.date.slice(5)}</div></td>
              <td><BandChip band={d.band} /></td>
              <td className="num">{fmt(d.htsi)}<div className="muted small">{d.lead ? `${fmt(d.q10, 0)}–${fmt(d.q90, 0)}` : "observed"}</div></td>
              <td className="num">{d.lead ? `${Math.round((d.pWarning ?? 0) * 100)}%` : "–"}</td>
              <td className="num">{fmt(d.mri, 0)}</td>
              <td className="num">{fmt(d.excessDeaths, 3)}<div className="muted small">{fmt(d.excessLow, 3)}–{fmt(d.excessHigh, 3)}</div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function WardPanel({ id, lead, meta, onClose }) {
  const ward = useData(`/wards/${id}`, [id]);
  const series = useData(`/series/${id}?days=30`, [id]);
  const explain = useData(`/explain/${id}?lead=${Math.max(lead, 1)}`, [id, lead]);
  const [lang, setLang] = useState("or");
  const [audience, setAudience] = useState("public");
  const advisory = useData(`/advisory/${id}?lang=${lang}&audience=${audience}`, [id, lang, audience]);
  const [sent, setSent] = useState(null);
  const { bump } = useApp();

  if (ward.loading && !ward.data) return <Loading what="Loading ward" />;
  if (ward.error) return <div role="alert">{ward.error}</div>;
  const w = ward.data;
  const d = w.days[lead];
  const hap = w.hap;

  const trigger = async () => {
    try {
      const r = await api.post("/hap/trigger", { scope: "ward", id: w.id, level: hap?.band === "Normal" ? "Watch" : hap.band, by: "dashboard", note: `Operator action from ward panel for ${w.name}` });
      setSent(`Heat Action Plan measures logged (${r.level}) — see Command.`);
      bump();
    } catch (e) {
      setSent(e.message);
    }
  };

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>{w.name}</h2>
          <div className="muted small">{w.ulb} · {w.districtName} district{w.synthetic ? " · synthetic ward" : ""}</div>
        </div>
        <button className="btn sm" onClick={onClose} aria-label="Close panel">✕</button>
      </div>

      <div className="row" style={{ marginTop: 10 }}>
        <span className="small muted">Heat Action Plan:</span>
        <BandChip band={hap?.band ?? "Normal"} large />
        {hap?.since && hap.level > 0 && <span className="small muted">since {hap.since}</span>}
      </div>
      {hap?.target?.reason && <div className="sentence">{hap.target.reason}</div>}

      <div className="statbar">
        <Stat k={lead === 0 ? "HTSI today" : `HTSI D+${lead}`} v={fmt(d.htsi, 0)} s={lead ? `80%: ${fmt(d.q10, 0)}–${fmt(d.q90, 0)}` : d.band} />
        <Stat k="Mortality Risk Index" v={fmt(d.mri, 0)} s={`RR ${fmt(d.rr, 3)}`} />
        <Stat k="Excess deaths" v={fmt(d.excessDeaths, 3)} s={`${fmt(d.excessLow, 3)}–${fmt(d.excessHigh, 3)} · ED +${fmt(d.edSurge, 1)}`} />
      </div>
      <div className="statbar">
        <Stat k="Peak WBGT" v={`${fmt(d.wbgt)}°`} s="daily max, with UHI" />
        <Stat k="Night WBGT" v={`${fmt(d.nightWbgt)}°`} s="22:00–06:00 min" />
        <Stat k={lead === 0 ? "Urban heat today" : `Urban heat D+${lead}`} v={`+${fmt(d.uhi)}`} s={`HTSI pts · built-up ${Math.round(w.builtUp * 100)}%`} />
      </div>

      <h3>Thermal stress, observed and forecast</h3>
      {series.data ? <ForecastChart series={series.data} edges={meta.bands.edges} /> : <Loading />}

      <h3>Why</h3>
      {explain.data ? (
        <div>
          <div className="sentence">{explain.data.sentence}</div>
          <div className="sentence">{explain.data.uhi.sentence}</div>
          <div className="sentence">{explain.data.risk.sentence}</div>
          {explain.data.drivers?.length > 0 && (
            <table className="data small" style={{ marginTop: 6 }}>
              <thead><tr><th>Model driver (SHAP, D+{explain.data.lead <= 1 ? 1 : explain.data.lead <= 3 ? 3 : 5})</th><th className="num">Value</th><th className="num">Effect on HTSI</th></tr></thead>
              <tbody>
                {explain.data.drivers.map((x) => (
                  <tr key={x.feature}><td>{x.label}</td><td className="num">{fmt(x.value)}</td><td className="num">{x.contribution >= 0 ? "+" : ""}{fmt(x.contribution)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : <Loading />}

      <h3>Next five days</h3>
      <DaysTable days={w.days} />

      <h3>Who lives here</h3>
      <div className="statbar">
        <Stat k="Population" v={fmtInt(w.population)} s={`${fmt(w.areaKm2)} km²`} />
        <Stat k="Aged 60+" v={`${fmt(w.elderlyPct)}%`} />
        <Stat k="In slums" v={`${fmt(w.slumPct)}%`} s={`vulnerability ×${fmt(w.vulnMult, 2)}`} />
      </div>

      <h3>Advisory</h3>
      <div className="row">
        <Seg options={LANGS} value={lang} onChange={setLang} label="Language" />
        <select value={audience} onChange={(e) => setAudience(e.target.value)} aria-label="Audience">
          {meta.audiences.map((a) => <option key={a} value={a}>{a.replace("_", " ")}</option>)}
        </select>
      </div>
      {advisory.data && (
        <div style={{ marginTop: 8 }}>
          {advisory.data.headline ? <b>{advisory.data.headline}</b> : <span className="muted">No alert in force — routine precautions only.</span>}
          <ul className="actions">{advisory.data.actions.map((a) => <li key={a}>{a}</li>)}</ul>
          {advisory.data.sms && <div className="sentence small"><b>SMS:</b> {advisory.data.sms}</div>}
          {lang !== "en" && <div className="muted small">{advisory.data.reviewStatus}</div>}
        </div>
      )}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" onClick={trigger} disabled={!hap || hap.level === 0}>Trigger Heat Action Plan</button>
        {hap?.alertId && <a className="btn" href={`/v1/alerts/${hap.alertId}/cap.xml`} target="_blank" rel="noreferrer">CAP 1.2 XML</a>}
        <a className="btn" href={`/field?ward=${w.id}`}>Field view</a>
      </div>
      {sent && <div className="small" role="status" style={{ marginTop: 6 }}>{sent}</div>}
    </div>
  );
}

export function DistrictPanel({ id, lead, onClose }) {
  const dq = useData(`/districts/${id}`, [id]);
  if (!dq.data) return <Loading />;
  const d = dq.data;
  const day = d.days[lead];
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>{d.name} district</h2>
          <div className="muted small">HQ {d.hq} · population {fmtInt(d.population)}</div>
        </div>
        <button className="btn sm" onClick={onClose} aria-label="Close panel">✕</button>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <span className="small muted">Heat Action Plan:</span>
        <BandChip band={d.hap?.band ?? "Normal"} large />
      </div>
      {d.hap?.target?.reason && <div className="sentence">{d.hap.target.reason}</div>}
      <div className="statbar">
        <Stat k="Mean HTSI" v={fmt(day.htsi, 0)} s={`hottest cell ${fmt(day.htsiMax, 0)}`} />
        <Stat k="MRI" v={fmt(day.mri, 0)} s={`RR ${fmt(day.rr, 3)}`} />
        <Stat k="Excess deaths" v={fmt(day.excessDeaths, 2)} s={`${fmt(day.excessLow, 2)}–${fmt(day.excessHigh, 2)}`} />
      </div>
      <h3>Vulnerability</h3>
      <div className="statbar">
        <Stat k="Rank" v={`${d.vulnerability.rank} / 30`} s={d.vulnerability.tier} />
        <Stat k="Exposure" v={fmt(d.vulnerability.exposure, 2)} s="0–1" />
        <Stat k="Low capacity" v={fmt(d.vulnerability.adaptive, 2)} s="0–1" />
      </div>
      <table className="data small">
        <tbody>
          <tr><td>Aged 60+</td><td className="num">{fmt(d.profile.elderlyPct)}%</td></tr>
          <tr><td>Household electricity (NFHS-5)</td><td className="num">{fmt(d.profile.electricityPct)}%</td></tr>
          <tr><td>Clean cooking fuel</td><td className="num">{fmt(d.profile.cleanFuelPct)}%</td></tr>
          <tr><td>Health insurance</td><td className="num">{fmt(d.profile.healthInsurancePct)}%</td></tr>
          <tr><td>High blood pressure, women / men</td><td className="num">{fmt(d.profile.womenHighBpPct)}% / {fmt(d.profile.menHighBpPct)}%</td></tr>
          <tr><td>Travel time to healthcare</td><td className="num">{fmt(d.profile.healthcareTravelMin, 0)} min</td></tr>
        </tbody>
      </table>
      <h3>Next five days</h3>
      <DaysTable days={d.days} />
    </div>
  );
}
