import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ErrorBar, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { useData } from "../lib/state.jsx";
import { Legend, Loading, Tile, VizTip } from "../components/ui.jsx";
import { fmt, fmtInt } from "../lib/bands.js";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function ChartCard({ title, sub, legend, table, children, tall }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>{title}</h2>
        <button className="btn sm" onClick={() => setAsTable(!asTable)} aria-pressed={asTable}>{asTable ? "Chart" : "Table"}</button>
      </div>
      {sub && <p className="small muted" style={{ margin: "4px 0 6px" }}>{sub}</p>}
      {asTable ? (
        <div className="table-wrap" style={{ maxHeight: 320 }}>
          <table className="data">
            <thead><tr>{table.cols.map((c) => <th key={c} className={c === table.cols[0] ? "" : "num"}>{c}</th>)}</tr></thead>
            <tbody>{table.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className={j ? "num" : ""}>{v}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : (
        <>
          {legend && <Legend items={legend} />}
          <div className={`chart${tall ? " tall" : ""}`}><ResponsiveContainer>{children}</ResponsiveContainer></div>
        </>
      )}
    </div>
  );
}

const axisProps = { tickLine: false, axisLine: { stroke: "var(--axis)" } };

export default function ValidationPage() {
  const { data: v, error } = useData("/validation");
  if (error) return <div className="page" role="alert">{error}</div>;
  if (!v) return <div className="page"><Loading /></div>;

  const a = v.alerts;
  const H = v.forecast.horizons;
  const leads = Object.keys(H).map(Number).sort();
  const summerWarn = (a.summerBandSharesPct.Warning ?? 0) + (a.summerBandSharesPct.Emergency ?? 0);

  const monthly = a.monthly.map((m) => ({ m: MONTHS[m.month - 1], USHMA: m.ushma, IMD: m.imd }));
  const skill = leads.map((h) => ({ lead: `D+${h}`, Model: H[h].mae_model, Persistence: H[h].mae_persistence, Climatology: H[h].mae_climatology }));
  const cover = leads.map((h) => ({ lead: `D+${h}`, "Raw quantiles": 100 * H[h].coverage_80_raw, "After conformal": 100 * H[h].coverage_80_conformal }));
  const E = v.forecast.exceedance ?? {};
  const f1 = leads.map((h) => ({
    lead: `D+${h}`,
    Classifier: E[h]?.warning.model.f1 ?? null,
    Persistence: E[h]?.warning.persistence.f1 ?? H[h].warning_persistence.f1,
    "Median forecast": H[h].warning_model.f1,
    auc: E[h]?.warning.auc,
  }));
  // Reliability of the Watch+ classifier: Warning+ is too rare for stable bins.
  const relSrc = (h) => E[h]?.watch.reliability ?? H[h].reliability;
  const rel = (h) => relSrc(h).filter((b) => b.observed != null && b.n >= 30).map((b) => ({ x: b.bin, y: b.observed, n: b.n }));
  const shap = (v.forecast.shap?.["1"] ?? []).slice(0, 10).map((s) => ({ f: s.label, v: s.mean_abs_shap }));
  const annual = v.risk.annual.map((r) => ({ y: String(r.year), excess: r.excess_deaths, err: [r.excess_deaths - r.excess_low, r.excess_high - r.excess_deaths], low: r.excess_low, high: r.excess_high, ncrb: r.ncrb_heatstroke }));
  const byMonth = Object.entries(v.risk.byMonth).map(([m, x]) => ({ m: MONTHS[m - 1], x }));
  const d1 = H[leads[0]];
  const d3 = H[3] ?? H[leads.at(-1)];

  return (
    <div className="page">
      <h1>Evidence</h1>
      <p className="lede">What the system gets right, measured — and what it cannot know. Every number here is computed from the supplied data by the pipeline; the heat–mortality curve is the one transferred component, and it is labelled as such.</p>

      <div className="tiles">
        <Tile k="Supplied notebook: days flagged Red" v={`${a.notebookRedDaysPct}%`} s="daily-max T paired with daily-mean RH" />
        <Tile k="USHMA summer days at Warning+" v={`${fmt(summerWarn)}%`} s="hourly indices, calibrated bands" />
        <Tile k="USHMA alerts a Tmax ≥ 40 °C rule misses" v={`${a.ushmaMissedByTempPct}%`} s={`mean Tmax ${a.missedMeanTmax} °C, WBGT ${a.missedMeanWbgt} °C`} />
        <Tile k="July–August alerts" v={`${fmtInt(a.julAugUshma)} vs ${a.julAugImd}`} s="USHMA vs temperature threshold" />
        <Tile k="D+1 forecast error" v={`${fmt(d1.mae_model, 2)} pts`} s={`persistence ${fmt(d1.mae_persistence, 2)} · skill ${Math.round(d1.skill_vs_persistence * 100)}%`} />
        <Tile k="80% band coverage (test)" v={`${Math.round(d1.coverage_80_conformal * 100)}%`} s="held-out 2024–25, after conformal calibration" />
        <Tile k="D+1 Warning-day detection" v={`AUC ${fmt(E[leads[0]]?.warning.auc, 2)}`} s={`F1 ${fmt(E[leads[0]]?.warning.model.f1, 2)} vs persistence ${fmt(E[leads[0]]?.warning.persistence.f1, 2)}`} />
      </div>

      <div className="grid two">
        <ChartCard title="When each system warns" sub="Share of in-state cell-days at Warning or above, by month, 2015–2025"
          legend={[{ label: "USHMA (HTSI Warning+)", color: "var(--s1)", box: true }, { label: "Temperature rule (Tmax ≥ 40 °C)", color: "var(--s2)", box: true }]}
          table={{ cols: ["Month", "USHMA %", "Tmax ≥ 40 °C %"], rows: monthly.map((r) => [r.m, fmt(r.USHMA, 2), fmt(r.IMD, 2)]) }}>
          <BarChart data={monthly} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barGap={2}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="m" {...axisProps} />
            <YAxis tickLine={false} axisLine={false} unit="%" />
            <Tooltip content={<VizTip fmt={(x) => `${fmt(x, 2)}%`} />} cursor={{ fill: "var(--surface-2)" }} />
            <Bar isAnimationActive={false} dataKey="USHMA" name="USHMA" fill="var(--s1)" radius={[4, 4, 0, 0]} />
            <Bar isAnimationActive={false} dataKey="IMD" name="Tmax ≥ 40 °C" fill="var(--s2)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Forecast error by lead time" sub="Mean absolute error of HTSI on held-out 2024–2025 (lower is better)"
          legend={[{ label: "USHMA model", color: "var(--s1)" }, { label: "Persistence", color: "var(--s2)" }, { label: "Climatology", color: "var(--s3)" }]}
          table={{ cols: ["Lead", "Model", "Persistence", "Climatology"], rows: skill.map((r) => [r.lead, fmt(r.Model, 2), fmt(r.Persistence, 2), fmt(r.Climatology, 2)]) }}>
          <LineChart data={skill} margin={{ top: 8, right: 80, left: -12, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="lead" {...axisProps} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip content={<VizTip fmt={(x) => fmt(x, 2)} />} />
            {[["Model", "var(--s1)"], ["Persistence", "var(--s2)"], ["Climatology", "var(--s3)"]].map(([k, c]) => (
              <Line key={k} dataKey={k} stroke={c} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: c }} isAnimationActive={false}>
                <LabelList dataKey={k} content={({ x, y, index }) => (index === skill.length - 1 ? <text x={x + 8} y={y + 4} fill="var(--ink-2)" fontSize={12}>{k}</text> : null)} />
              </Line>
            ))}
          </LineChart>
        </ChartCard>

        <ChartCard title="Are the uncertainty bands honest?" sub="Share of outcomes inside the stated 80% band, held-out 2024–2025"
          legend={[{ label: "Raw quantiles", color: "var(--s2)" }, { label: "After split-conformal calibration", color: "var(--s1)" }]}
          table={{ cols: ["Lead", "Raw %", "Conformal %"], rows: cover.map((r) => [r.lead, fmt(r["Raw quantiles"]), fmt(r["After conformal"])]) }}>
          <LineChart data={cover} margin={{ top: 8, right: 60, left: -12, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="lead" {...axisProps} />
            <YAxis domain={[50, 100]} tickLine={false} axisLine={false} unit="%" />
            <ReferenceLine y={80} stroke="var(--ink-3)" strokeDasharray="4 4" label={{ value: "target 80%", position: "right", fill: "var(--ink-3)", fontSize: 11 }} />
            <Tooltip content={<VizTip fmt={(x) => `${fmt(x)}%`} />} />
            <Line dataKey="Raw quantiles" stroke="var(--s2)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: "var(--s2)" }} isAnimationActive={false} />
            <Line dataKey="After conformal" stroke="var(--s1)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: "var(--s1)" }} isAnimationActive={false} />
          </LineChart>
        </ChartCard>

        <ChartCard title="Catching Warning days" sub="F1 for Warning-or-worse days (1.1% of test days). The median forecast never reaches them, which is why a dedicated exceedance classifier drives the alerts."
          legend={[{ label: "Exceedance classifier", color: "var(--s1)", box: true }, { label: "Persistence", color: "var(--s2)", box: true }, { label: "Median forecast", color: "var(--s3)", box: true }]}
          table={{ cols: ["Lead", "Classifier F1", "Persistence F1", "Median F1", "Classifier AUC"], rows: f1.map((r) => [r.lead, fmt(r.Classifier, 3), fmt(r.Persistence, 3), fmt(r["Median forecast"], 3), fmt(r.auc, 3)]) }}>
          <BarChart data={f1} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barGap={2}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="lead" {...axisProps} />
            <YAxis domain={[0, 0.4]} tickLine={false} axisLine={false} />
            <Tooltip content={<VizTip fmt={(x) => fmt(x, 3)} />} cursor={{ fill: "var(--surface-2)" }} />
            <Bar isAnimationActive={false} dataKey="Classifier" fill="var(--s1)" radius={[4, 4, 0, 0]}>
              <LabelList dataKey="Classifier" position="top" formatter={(x) => fmt(x, 2)} fill="var(--ink-2)" fontSize={11} />
            </Bar>
            <Bar isAnimationActive={false} dataKey="Persistence" fill="var(--s2)" radius={[4, 4, 0, 0]} />
            <Bar isAnimationActive={false} dataKey="Median forecast" fill="var(--s3)" radius={[4, 4, 0, 0]} minPointSize={0} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Reliability of P(Watch+)" sub="Classifier probability vs observed frequency on held-out data (bins with ≥ 30 cases); the diagonal is perfect calibration"
          legend={[{ label: "D+1", color: "var(--s1)" }, { label: "D+3", color: "var(--s2)" }]}
          table={{ cols: ["Bin", "D+1 observed", "D+3 observed"], rows: relSrc(leads[0]).map((b, i) => [fmt(b.bin, 2), fmt(b.observed, 3), fmt(relSrc(3)[i]?.observed, 3)]) }}>
          <ScatterChart margin={{ top: 8, right: 16, left: -12, bottom: 0 }}>
            <CartesianGrid />
            <XAxis type="number" dataKey="x" domain={[0, 1]} name="forecast" {...axisProps} />
            <YAxis type="number" dataKey="y" domain={[0, 1]} name="observed" tickLine={false} axisLine={false} />
            <ZAxis range={[80, 80]} />
            <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--ink-3)" strokeDasharray="4 4" />
            <Tooltip content={<VizTip fmt={(x) => fmt(x, 2)} title={() => "Reliability bin"} />} />
            <Scatter name="D+1" data={rel(leads[0])} fill="var(--s1)" line={{ stroke: "var(--s1)", strokeWidth: 2 }} />
            <Scatter name="D+3" data={rel(3)} fill="var(--s2)" line={{ stroke: "var(--s2)", strokeWidth: 2 }} />
          </ScatterChart>
        </ChartCard>

        <ChartCard title="What drives the D+1 forecast" sub="Mean |SHAP| contribution to HTSI, held-out sample"
          table={{ cols: ["Feature", "Mean |SHAP|"], rows: shap.map((s) => [s.f, fmt(s.v, 2)]) }} tall>
          <BarChart data={shap} layout="vertical" margin={{ top: 4, right: 40, left: 90, bottom: 0 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" {...axisProps} />
            <YAxis type="category" dataKey="f" width={170} tickLine={false} axisLine={false} />
            <Tooltip content={<VizTip fmt={(x) => fmt(x, 2)} />} cursor={{ fill: "var(--surface-2)" }} />
            <Bar isAnimationActive={false} dataKey="v" name="Mean |SHAP|" fill="var(--s1)" radius={[0, 4, 4, 0]}>
              <LabelList dataKey="v" position="right" formatter={(x) => fmt(x, 1)} fill="var(--ink-2)" fontSize={12} />
            </Bar>
          </BarChart>
        </ChartCard>

        <ChartCard title="Heat-attributable deaths, Odisha" sub="Annual total with the range implied by the transferred risk curve. NCRB certified heatstroke deaths (2023: 73) are a small, under-ascertained subset."
          table={{ cols: ["Year", "Central", "Low", "High", "NCRB heatstroke"], rows: annual.map((r) => [r.y, fmtInt(r.excess), fmtInt(r.low), fmtInt(r.high), r.ncrb ?? "–"]) }}>
          <BarChart data={annual} margin={{ top: 16, right: 8, left: -4, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="y" {...axisProps} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip content={<VizTip fmt={(x) => (Array.isArray(x) ? "" : fmtInt(x))} />} cursor={{ fill: "var(--surface-2)" }} />
            <Bar isAnimationActive={false} dataKey="excess" name="Attributable deaths" fill="var(--s1)" radius={[4, 4, 0, 0]}>
              <ErrorBar dataKey="err" width={6} stroke="var(--ink-2)" strokeWidth={1.5} />
            </Bar>
          </BarChart>
        </ChartCard>

        <ChartCard title="When heat kills, by month" sub="Modelled attributable deaths summed over 2015–2025"
          table={{ cols: ["Month", "Deaths"], rows: byMonth.map((r) => [r.m, fmtInt(r.x)]) }}>
          <BarChart data={byMonth} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="m" {...axisProps} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip content={<VizTip fmt={(x) => fmtInt(x)} />} cursor={{ fill: "var(--surface-2)" }} />
            <Bar isAnimationActive={false} dataKey="x" name="Attributable deaths" fill="var(--s1)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartCard>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h2>What this system cannot know</h2>
        <ul>
          <li>The supplied mortality (2007–2011) and weather (2015–2025) records share no days, so the heat–mortality curve is transferred from published tropical studies, not fitted here.</li>
          <li>The mortality file duplicated 23,269 records across two survey rounds in 14 districts; those are removed before any rate is estimated.</li>
          <li>The weather grid is ~27 km. Ward values are an interpolation plus an urban-heat-island parameterisation, and the ward geometry is synthetic until real boundaries are supplied.</li>
          <li>Intervention effect sizes on the Cooling centres page are planning assumptions.</li>
        </ul>
      </div>
    </div>
  );
}
