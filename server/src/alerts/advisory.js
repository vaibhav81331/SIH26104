// Audience-targeted, trilingual advisories.
//
// Text lives in i18n/{en,hi,or}.json so translations can be reviewed and
// corrected by people who speak the language, without touching code. Odia and
// Hindi are marked as drafts pending native-speaker review.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "i18n");
export const LANGS = Object.fromEntries(
  ["en", "hi", "or"].map((l) => [l, JSON.parse(fs.readFileSync(path.join(dir, `${l}.json`), "utf8"))]),
);
export const AUDIENCES = Object.keys(LANGS.en.audiences);

// Odia and Devanagari digits, so a number in an SMS reads naturally.
const DIGITS = { or: "୦୧୨୩୪୫୬୭୮୯", hi: null, en: null };

function localiseDigits(s, lang) {
  const d = DIGITS[lang];
  return d ? String(s).replace(/[0-9]/g, (c) => d[Number(c)]) : String(s);
}

function fill(template, vars, lang) {
  return template.replace(/\{(\w+)\}/g, (_, k) => {
    const v = vars[k];
    if (v === undefined || v === null) return "";
    return typeof v === "number" ? localiseDigits(v, lang) : String(v);
  });
}

export function dayPhrase(lead, date, lang) {
  const t = (LANGS[lang] ?? LANGS.en).days;
  if (lead === 0) return t.today;
  if (lead === 1) return t.tomorrow;
  // Dates are localised too, so an Odia SMS carries no stray ASCII digits.
  return fill(t.onDate, { date: localiseDigits(date ?? "", lang) }, lang);
}

const round = (v, d = 0) => (v == null ? null : Number(Number(v).toFixed(d)));

/**
 * Render an advisory for one place.
 * @param {object} p  { place, level, lead, day:{date,htsi,wbgt,nightWbgt,excessDeaths,...} }
 */
export function renderAdvisory({ place, level, lead = 0, day, lang = "en", audience = "public" }) {
  const L = LANGS[lang] ?? LANGS.en;
  const aud = L.audiences[audience] ?? L.audiences.public;
  const vars = {
    place,
    day: dayPhrase(lead, day?.date, lang),
    htsi: round(day?.htsi),
    wbgt: round(day?.wbgt, 1),
    night: round(day?.nightWbgt, 1),
    level: L.levels[level] ?? level,
    excess: round(day?.excessDeaths, 1),
    excessLow: round(day?.excessLow, 1),
    excessHigh: round(day?.excessHigh, 1),
    ed: round(day?.edSurge),
  };
  const actionable = level !== "Normal";
  return {
    language: lang,
    languageName: L._meta.language,
    reviewStatus: L._meta.review,
    audience,
    audienceLabel: aud.label,
    level,
    levelLabel: L.levels[level] ?? level,
    headline: actionable ? fill(L.headline[level], vars, lang) : null,
    sms: actionable ? fill(L.sms[level], vars, lang) : null,
    description: fill(L.description, vars, lang),
    actions: actionable ? (aud[level] ?? []).map((a) => fill(a, vars, lang)) : [],
  };
}
