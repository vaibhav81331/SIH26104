import { useEffect, useMemo, useState } from "react";
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { useApp, useData } from "../lib/state.jsx";
import { BAND_STYLE, BANDS, LAYERS, SEQ, fmt, seqColor } from "../lib/bands.js";
import { BandChip, Loading, Seg } from "../components/ui.jsx";
import { DistrictPanel, WardPanel } from "../components/PlacePanel.jsx";

const CITIES = {
  Bhubaneswar: [20.2961, 85.8245], Cuttack: [20.4625, 85.883], Berhampur: [19.3149, 84.7941], Sambalpur: [21.4669, 83.9812],
  Rourkela: [22.2604, 84.8536], Puri: [19.8135, 85.8312], Balasore: [21.4942, 86.9317], Balangir: [20.7074, 83.4843],
};

function FlyTo({ target }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo(target.center, target.zoom, { duration: 0.8 });
  }, [target, map]);
  return null;
}

function colourFor(layer, v, max) {
  if (layer === "htsi") return BAND_STYLE[v?.band ?? "Normal"].hex;
  const x = layer === "mri" ? v?.mri : layer === "excess" ? v?.rate : v?.vuln;
  return seqColor(x, max);
}

function MapLegend({ layer, max }) {
  if (layer === "htsi") {
    return (
      <>
        <b className="small">Heat band (HTSI)</b>
        {BANDS.map((b) => (
          <div className="legend-row" key={b}>
            <span className="legend-swatch" style={{ background: BAND_STYLE[b].hex }} />
            <span aria-hidden="true">{BAND_STYLE[b].icon}</span> {b}
          </div>
        ))}
      </>
    );
  }
  return (
    <>
      <b className="small">{LAYERS[layer].label}</b>
      <div className="row" style={{ gap: 0, marginTop: 6 }}>
        {SEQ.map((c) => <span key={c} style={{ background: c, width: 28, height: 12 }} />)}
      </div>
      <div className="row small muted" style={{ justifyContent: "space-between" }}>
        <span>0</span><span>{layer === "vuln" ? "1.0" : fmt(max, layer === "excess" ? 3 : 0)}+</span>
      </div>
    </>
  );
}

function Overview({ snap, onPick }) {
  const active = useData("/alerts/active?scope=ward");
  const counts = useMemo(() => {
    const c = { Normal: 0, Watch: 0, Warning: 0, Emergency: 0 };
    for (const w of Object.values(snap?.wards ?? {})) c[w.band] = (c[w.band] ?? 0) + 1;
    return c;
  }, [snap]);
  if (!snap) return <Loading />;
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Odisha · {snap.lead === 0 ? `today, ${snap.date}` : `D+${snap.lead}, ${snap.date}`}</h2>
      <div className="statbar">
        <div className="stat"><div className="k">Heat-attributable deaths</div><div className="v">{fmt(snap.statewide.excess, 1)}</div><div className="s">{fmt(snap.statewide.excessLow, 1)}–{fmt(snap.statewide.excessHigh, 1)} statewide</div></div>
        <div className="stat"><div className="k">Wards Warning+</div><div className="v">{counts.Warning + counts.Emergency}</div><div className="s">of {Object.keys(snap.wards).length}</div></div>
        <div className="stat"><div className="k">Districts Warning+</div><div className="v">{Object.values(snap.districts).filter((d) => ["Warning", "Emergency"].includes(d.band)).length}</div><div className="s">of 30</div></div>
      </div>
      <div className="row small">
        {BANDS.map((b) => <BandChip key={b} band={b} suffix={<span className="muted"> {counts[b]}</span>} />)}
      </div>
      <h3>Heat Action Plan in force</h3>
      {!active.data ? <Loading /> : active.data.alerts.length === 0 ? (
        <div className="muted small">No ward is under a Watch or higher as of {active.data.asOf}.</div>
      ) : (
        <table className="data">
          <thead><tr><th>Ward</th><th>Level</th><th>Triggered by</th><th className="num">MRI peak</th></tr></thead>
          <tbody>
            {active.data.alerts.slice(0, 25).map((a) => (
              <tr key={a.key} className="click" onClick={() => onPick({ kind: "ward", id: a.id })}>
                <td>{a.name}<div className="muted small">{a.city}</div></td>
                <td><BandChip band={a.band} /></td>
                <td className="small">
                  {a.target?.trigger?.lead ? `D+${a.target.trigger.lead} forecast` : "today"}
                  <div className="muted">HTSI {fmt(a.target?.trigger?.htsi, 0)}{a.target?.trigger?.pWarning != null && a.target.trigger.lead ? ` · P(Warn) ${Math.round(a.target.trigger.pWarning * 100)}%` : ""}</div>
                </td>
                <td className="num">{fmt(Math.max(a.today?.mri ?? 0, ...(a.forecast ?? []).slice(0, 3).map((f) => f.mri ?? 0)), 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="small muted" style={{ marginTop: 12 }}>
        Grid cells are the model's native 0.25° (~27 km) resolution. Wards add inverse-distance interpolation and an urban-heat-island uplift.
        Click any ward, district marker or cell.
      </p>
    </div>
  );
}

export default function MapPage() {
  const { meta } = useApp();
  const [lead, setLead] = useState(0);
  const [layer, setLayer] = useState("htsi");
  const [sel, setSel] = useState(null);
  const [fly, setFly] = useState(null);
  const cells = useData("/cells");
  const wards = useData("/wards");
  const districts = useData("/districts");
  const snapQ = useData(`/snapshot?lead=${lead}`, [lead]);
  const snap = snapQ.data;

  const wardProps = useMemo(() => Object.fromEntries((wards.data?.features ?? []).map((f) => [f.properties.id, f.properties])), [wards.data]);
  const distProps = useMemo(() => Object.fromEntries((districts.data ?? []).map((d) => [String(d.id), d])), [districts.data]);

  // Excess deaths are mapped as a RATE per 100,000 per day. Absolute counts on a
  // choropleth mostly map where people live, not where risk is high.
  const wardRate = (id) => (snap?.wards?.[id]?.excess ?? 0) / Math.max(wardProps[id]?.population ?? 1, 1) * 1e5;
  const distRate = (id) => (snap?.districts?.[id]?.excess ?? 0) / Math.max(distProps[id]?.population ?? 1, 1) * 1e5;
  const rateMax = useMemo(() => {
    if (!snap) return 0.1;
    const xs = Object.keys(snap.wards).map(wardRate).sort((a, b) => a - b);
    return Math.max(xs[Math.floor(xs.length * 0.95)] ?? 0, 0.02);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap, wardProps]);
  const max = layer === "excess" ? rateMax : layer === "mri" ? 60 : 1;

  if (!meta) return <div className="page"><Loading what="Connecting to USHMA" /></div>;
  const key = `${layer}-${lead}-${snap?.asOf}`;

  const cellStyle = (f) => {
    const v = snap?.cells?.[f.properties.id];
    const d = snap?.districts?.[String(f.properties.district)];
    let fill;
    if (layer === "htsi") {
      const band = v >= meta.bands.edges[2] ? "Emergency" : v >= meta.bands.edges[1] ? "Warning" : v >= meta.bands.edges[0] ? "Watch" : "Normal";
      fill = BAND_STYLE[band].hex;
    } else {
      const id = String(f.properties.district);
      fill = colourFor(layer, { ...d, vuln: distProps[id]?.vulnerability.score, rate: distRate(id) }, max);
    }
    return { color: "#ffffff", weight: 0.4, fillColor: fill, fillOpacity: layer === "htsi" ? 0.55 : 0.6 };
  };
  const wardStyle = (f) => {
    const v = snap?.wards?.[f.properties.id];
    return {
      color: sel?.id === f.properties.id ? "#0b0b0b" : "#ffffff",
      weight: sel?.id === f.properties.id ? 2.5 : 0.8,
      fillColor: colourFor(layer, { ...v, vuln: wardProps[f.properties.id]?.vulnScore, rate: wardRate(f.properties.id) }, max),
      fillOpacity: 0.85,
    };
  };

  return (
    <div className="mapwrap">
      <div className="map">
        <MapContainer center={[20.4, 84.6]} zoom={7} minZoom={6} maxZoom={15} preferCanvas zoomControl>
          <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}" maxZoom={16} attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors" opacity={0.55} />
          <FlyTo target={fly} />
          {cells.data && snap && (
            <GeoJSON key={`c-${key}`} data={cells.data} style={cellStyle}
              onEachFeature={(f, l) => {
                l.on("click", () => setSel({ kind: "district", id: String(f.properties.district) }));
                l.bindTooltip(() => `Grid cell ${f.properties.lat.toFixed(2)}°N ${f.properties.lon.toFixed(2)}°E · HTSI ${fmt(snap.cells[f.properties.id])}`, { className: "ushma-tip", sticky: true });
              }} />
          )}
          {wards.data && snap && (
            <GeoJSON key={`w-${key}-${sel?.id}`} data={wards.data} style={wardStyle}
              onEachFeature={(f, l) => {
                const v = snap.wards[f.properties.id];
                l.on("click", (e) => { e.originalEvent?.stopPropagation?.(); setSel({ kind: "ward", id: f.properties.id }); });
                l.bindTooltip(`<b>${f.properties.name}</b><br/>${v.band} · HTSI ${fmt(v.htsi)} · MRI ${fmt(v.mri, 0)}<br/>excess ${fmt(v.excess, 3)} deaths/day`, { className: "ushma-tip", sticky: true });
              }} />
          )}
          {districts.data && snap && districts.data.map((d) => {
            const v = snap.districts[String(d.id)];
            return (
              <CircleMarker key={`${d.id}-${key}`} center={[d.lat, d.lon]} radius={7}
                pathOptions={{ color: "#ffffff", weight: 2, fillColor: BAND_STYLE[v?.hap ?? "Normal"].hex, fillOpacity: 1 }}
                eventHandlers={{ click: () => setSel({ kind: "district", id: String(d.id) }) }}>
                <Tooltip className="ushma-tip">{d.name}: HAP {v?.hap} · mean HTSI {fmt(v?.htsi)}</Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>

        <div className="overlay tl">
          <Seg label="Map layer" value={layer} onChange={setLayer}
            options={[["htsi", "Heat band"], ["mri", "Mortality risk"], ["excess", "Excess deaths /100k"], ["vuln", "Vulnerability"]]} />
          <div className="leadslider">
            <label htmlFor="lead" className="small">Lead</label>
            <input id="lead" type="range" min="0" max="5" value={lead} onChange={(e) => setLead(Number(e.target.value))} />
            <b className="small" style={{ minWidth: 110 }}>{lead === 0 ? "Today" : `D+${lead}`} {snap?.date ? `· ${snap.date.slice(5)}` : ""}</b>
          </div>
          <select aria-label="Zoom to city" onChange={(e) => {
            const c = e.target.value;
            setFly(c === "state" ? { center: [20.4, 84.6], zoom: 7 } : { center: CITIES[c], zoom: 12 });
          }} defaultValue="">
            <option value="" disabled>Zoom to…</option>
            <option value="state">All Odisha</option>
            {Object.keys(CITIES).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="overlay bl"><MapLegend layer={layer} max={max} /></div>
      </div>

      <aside className="side" aria-label="Details">
        {sel?.kind === "ward" ? (
          <WardPanel id={sel.id} lead={lead} meta={meta} onClose={() => setSel(null)} />
        ) : sel?.kind === "district" ? (
          <DistrictPanel id={sel.id} lead={lead} onClose={() => setSel(null)} />
        ) : (
          <Overview snap={snap} onPick={(p) => { setSel(p); const f = wards.data?.features.find((x) => x.properties.id === p.id); if (f) setFly({ center: [f.properties.lat, f.properties.lon], zoom: 13 }); }} />
        )}
      </aside>
    </div>
  );
}
