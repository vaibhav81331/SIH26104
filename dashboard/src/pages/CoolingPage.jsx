import { useEffect, useMemo, useState } from "react";
import { Circle, CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import { useApp, useData } from "../lib/state.jsx";
import { api } from "../lib/api.js";
import { SEQ, fmt, seqColor } from "../lib/bands.js";
import { Loading, Tile } from "../components/ui.jsx";

const CITIES = {
  Bhubaneswar: [20.2961, 85.8245], Cuttack: [20.4625, 85.883], Berhampur: [19.3149, 84.7941], Sambalpur: [21.4669, 83.9812],
  Rourkela: [22.2604, 84.8536], Puri: [19.8135, 85.8312], Balasore: [21.4942, 86.9317], Balangir: [20.7074, 83.4843],
};

export default function CoolingPage() {
  const { version } = useApp();
  const [city, setCity] = useState("Bhubaneswar");
  const [n, setN] = useState(8);
  const [radius, setRadius] = useState(1.5);
  const [work, setWork] = useState(true);
  const [adv, setAdv] = useState(true);
  const [res, setRes] = useState(null);
  const [cf, setCf] = useState(null);
  const [err, setErr] = useState(null);
  const wards = useData("/wards");

  useEffect(() => {
    let alive = true;
    setErr(null);
    Promise.all([
      api.post("/optimize/cooling-centres", { city, n, radiusKm: radius }),
      api.post("/counterfactual", { city, coolingCentres: n, radiusKm: radius, workHourShift: work, targetedAdvisories: adv }),
    ])
      .then(([a, b]) => alive && (setRes(a), setCf(b)))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [city, n, radius, work, adv, version]);

  const cityWards = useMemo(
    () => (wards.data ? { ...wards.data, features: wards.data.features.filter((f) => f.properties.city === city) } : null),
    [wards.data, city],
  );
  const covered = new Set(res?.centres.flatMap((c) => c.newlyCoveredWards) ?? []);

  // Colour wards by forecast excess-death rate over D+1..D+3.
  const snap = useData("/snapshot?lead=1");
  const rate = (f) => ((snap.data?.wards?.[f.properties.id]?.excess ?? 0) / Math.max(f.properties.population, 1)) * 1e5;
  const rmax = useMemo(() => {
    if (!cityWards || !snap.data) return 0.05;
    const xs = cityWards.features.map(rate).sort((a, b) => a - b);
    return Math.max(xs[Math.floor(xs.length * 0.95)] ?? 0, 0.01);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cityWards, snap.data]);

  return (
    <div className="page">
      <h1>Cooling centres</h1>
      <p className="lede">
        “I can open N cooling centres in this city tomorrow. Where?” Sites are chosen to cover the most forecast heat-attributable deaths over the next three days
        within walking distance, then the effect of the chosen measures is projected with its uncertainty.
      </p>
      <div className="card row" style={{ marginBottom: 14 }}>
        <label className="field">City
          <select value={city} onChange={(e) => setCity(e.target.value)}>{Object.keys(CITIES).map((c) => <option key={c}>{c}</option>)}</select>
        </label>
        <label className="field">Centres: <b>{n}</b>
          <input type="range" min="1" max="30" value={n} onChange={(e) => setN(Number(e.target.value))} />
        </label>
        <label className="field">Walking radius: <b>{radius} km</b>
          <input type="range" min="0.5" max="4" step="0.25" value={radius} onChange={(e) => setRadius(Number(e.target.value))} />
        </label>
        <label className="row small"><input type="checkbox" checked={work} onChange={(e) => setWork(e.target.checked)} /> Shift outdoor work out of 11:00–16:00</label>
        <label className="row small"><input type="checkbox" checked={adv} onChange={(e) => setAdv(e.target.checked)} /> Targeted SMS / WhatsApp advisories</label>
      </div>
      {err && <div className="sentence" role="alert">{err}</div>}

      {cf && res && (
        <div className="tiles">
          <Tile k="Forecast heat deaths, D+1–3" v={fmt(cf.baseline.excess, 2)} s={`range ${fmt(cf.baseline.low, 2)}–${fmt(cf.baseline.high, 2)} · ${city}`} />
          <Tile k="Projected deaths averted" v={fmt(cf.averted.excess, 2)} s={`range ${fmt(cf.averted.low, 2)}–${fmt(cf.averted.high, 2)}`} />
          <Tile k="Risk inside coverage" v={`${Math.round(res.coveredRiskShare * 100)}%`} s={`${res.coveredWards} of ${res.totalWards} wards within ${radius} km`} />
          <Tile k="As of" v={res.asOf} s="forecast issuance date" />
        </div>
      )}

      <div className="grid two">
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ height: 520 }}>
            {cityWards && (
              <MapContainer key={city} center={CITIES[city]} zoom={12} style={{ height: "100%" }} preferCanvas>
                <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}" maxZoom={16} attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors" opacity={0.5} />
                <GeoJSON key={`${city}-${snap.data?.asOf}-${res?.centres.length}`} data={cityWards}
                  style={(f) => ({ color: covered.has(f.properties.id) ? "#0b0b0b" : "#ffffff", weight: covered.has(f.properties.id) ? 1.5 : 0.6, fillColor: seqColor(rate(f), rmax), fillOpacity: 0.8 })}
                  onEachFeature={(f, l) => l.bindTooltip(`${f.properties.name}: ${fmt(rate(f), 3)} excess deaths /100k/day (D+1)${covered.has(f.properties.id) ? " · covered" : ""}`, { className: "ushma-tip", sticky: true })} />
                {res?.centres.map((c) => (
                  <Circle key={`r${c.wardId}`} center={[c.lat, c.lon]} radius={radius * 1000} pathOptions={{ color: "#b8321f", weight: 1, fillOpacity: 0.04, dashArray: "4 4" }} />
                ))}
                {res?.centres.map((c) => (
                  <CircleMarker key={c.wardId} center={[c.lat, c.lon]} radius={9} pathOptions={{ color: "#ffffff", weight: 2, fillColor: "#b8321f", fillOpacity: 1 }}>
                    <Tooltip permanent direction="center" className="ushma-tip">{c.rank}</Tooltip>
                  </CircleMarker>
                ))}
              </MapContainer>
            )}
          </div>
          <div style={{ padding: "8px 12px" }} className="row small">
            <span>Excess deaths /100k/day:</span>
            {SEQ.map((c) => <span key={c} style={{ background: c, width: 22, height: 10, display: "inline-block" }} />)}
            <span className="muted">0 – {fmt(rmax, 3)}+</span>
            <span>· numbered markers = recommended centres, in priority order</span>
          </div>
        </div>

        <div className="card">
          <h2>Recommended sites</h2>
          {!res ? <Loading /> : (
            <table className="data">
              <thead><tr><th className="num">#</th><th>Site (ward)</th><th className="num">New wards covered</th></tr></thead>
              <tbody>
                {res.centres.map((c) => (
                  <tr key={c.wardId}><td className="num">{c.rank}</td><td>{c.name}</td><td className="num">{c.newlyCoveredWards.length}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          {cf && (
            <>
              <h3>Assumptions</h3>
              <ul className="small">
                <li>Cooling-centre access averts {Math.round(cf.assumptions.coolingCentreAvertedFraction * 100)}% of excess deaths in covered wards.</li>
                {work && <li>Shifting outdoor work averts {Math.round(cf.assumptions.workHourShiftAvertedFraction * 100)}%.</li>}
                {adv && <li>Targeted advisories avert {Math.round(cf.assumptions.advisoryReachAvertedFraction * 100)}%.</li>}
                <li>Effects combine multiplicatively on the remaining risk. {cf.assumptions.note}</li>
              </ul>
              <p className="small muted">{res.method}. Sites are ward centroids; in deployment these are replaced by real candidate buildings (schools, community halls, temples).</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
