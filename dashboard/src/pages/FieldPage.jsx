// Field view for ASHA and anganwadi workers: one ward, today's level, three
// things to do, in the worker's language. Large type, works on a small phone,
// and the service worker keeps the last-loaded advisory available offline.

import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api.js";
import { BAND_STYLE } from "../lib/bands.js";

const LANGS = [["or", "ଓଡ଼ିଆ"], ["hi", "हिन्दी"], ["en", "English"]];
const UI = {
  or: { ward: "ୱାର୍ଡ", today: "ଆଜି", tomorrow: "କାଲି", todo: "ଆଜି କଣ କରିବେ", share: "SMS କପି କରନ୍ତୁ", copied: "କପି ହେଲା", offline: "ଅଫଲାଇନ — ଶେଷ ସଞ୍ଚିତ ତଥ୍ୟ", peak: "ସର୍ବାଧିକ ଗରମ" },
  hi: { ward: "वार्ड", today: "आज", tomorrow: "कल", todo: "आज क्या करें", share: "SMS कॉपी करें", copied: "कॉपी हो गया", offline: "ऑफ़लाइन — अंतिम सहेजा डेटा", peak: "सबसे अधिक गर्मी" },
  en: { ward: "Ward", today: "Today", tomorrow: "Tomorrow", todo: "What to do today", share: "Copy SMS", copied: "Copied", offline: "Offline — showing last saved data", peak: "Hottest day" },
};

function readPref(k, d) {
  try {
    return localStorage.getItem(k) ?? d;
  } catch {
    return d;
  }
}
function writePref(k, v) {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* storage unavailable */
  }
}

export default function FieldPage() {
  const [params, setParams] = useSearchParams();
  const [wards, setWards] = useState([]);
  const [lang, setLang] = useState(() => readPref("ushma.field.lang", "or"));
  const [data, setData] = useState(null);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [copied, setCopied] = useState(false);
  const wardId = params.get("ward") || readPref("ushma.field.ward", "BBS-01");

  useEffect(() => {
    api.get("/wards").then((g) => setWards(g.features.map((f) => f.properties))).catch(() => {});
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  useEffect(() => {
    writePref("ushma.field.ward", wardId);
    writePref("ushma.field.lang", lang);
    api.get(`/field/${wardId}?lang=${lang}`).then(setData).catch(() => setData(null));
  }, [wardId, lang]);

  const cities = useMemo(() => [...new Set(wards.map((w) => w.city))], [wards]);
  const t = UI[lang];
  const s = BAND_STYLE[data?.level ?? "Normal"];

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(data.sms ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="field" lang={lang === "or" ? "or" : lang === "hi" ? "hi" : "en"}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <Link to="/" className="brand" style={{ textDecoration: "none", color: "inherit" }}>
          <img src="/icon.svg" alt="" width="26" height="26" /> USHMA
        </Link>
        <div className="seg" role="group" aria-label="Language">
          {LANGS.map(([k, l]) => (
            <button key={k} aria-pressed={lang === k} onClick={() => setLang(k)}>{l}</button>
          ))}
        </div>
      </div>

      <label className="field" style={{ marginTop: 12 }}>
        {t.ward}
        <select value={wardId} onChange={(e) => setParams({ ward: e.target.value })} style={{ fontSize: 17, padding: 10 }}>
          {cities.map((c) => (
            <optgroup key={c} label={c}>
              {wards.filter((w) => w.city === c).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </optgroup>
          ))}
        </select>
      </label>

      {offline && <div className="sentence small" role="status">{t.offline}</div>}

      {data && (
        <>
          <div className="hero" style={{ background: s.hex }} role="status" aria-live="polite">
            <div className="lvl"><span aria-hidden="true">{s.icon} </span>{data.levelLabel}</div>
            <div className="sub">
              {t.today}: {BAND_STYLE[data.today.band].icon} {data.today.label ?? data.today.band} · {t.tomorrow}: {BAND_STYLE[data.tomorrow.band].icon} {data.tomorrow.label ?? data.tomorrow.band}
            </div>
            <div className="sub">{t.peak}: {data.peak.lead === 0 ? t.today : data.peak.date} ({data.peak.label ?? data.peak.band})</div>
          </div>
          <h2 style={{ fontSize: 18, marginBottom: 0 }}>{t.todo}</h2>
          <ol>{data.actions.slice(0, 3).map((a) => <li key={a}>{a}</li>)}</ol>
          {data.sms && (
            <>
              <div className="sms">{data.sms}</div>
              <button className="btn primary" style={{ marginTop: 10, fontSize: 17, padding: "10px 16px" }} onClick={copy}>
                {copied ? t.copied : t.share}
              </button>
            </>
          )}
          <p className="small muted" style={{ marginTop: 16 }}>
            {data.name} · {data.city} · as of {data.asOf}
            {data.synthetic ? " · demonstration ward" : ""}
          </p>
        </>
      )}
    </div>
  );
}
