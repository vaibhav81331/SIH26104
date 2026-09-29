// Evaluate Heat Action Plan operating points over the whole replay season.
//
//   node scripts/evaluate-hap.js
//
// For each candidate configuration, replays every ward day by day and reports:
//   * share of ward-days at Warning+ and Watch+ (alert burden)
//   * share of observed Warning+ days that were already under a Watch / a
//     Warning the day before (anticipation)
//   * level changes per ward per season (stability)
// The default in src/config.js was chosen from this table; see docs/09.

import { ServeStore } from "../src/data/store.js";
import { runSequence } from "../src/alerts/hap.js";
import { config } from "../src/config.js";

const store = new ServeStore();
const edges = store.bandEdges;
const dates = store.replayDates;
const ids = Object.keys(store.replay.get(dates[0]).wards);
const band = (d, id) => store.replay.get(d).wards[id].days[0].band;
const isWarn = (b) => b === "Warning" || b === "Emergency";

function scale(th, k) {
  if (!th) return null;
  return Object.fromEntries(Object.entries(th).map(([h, v]) => [h, {
    warning: { threshold: Math.min(0.95, v.warning.threshold * k) },
    watch: { threshold: Math.min(0.95, v.watch.threshold * k) },
  }]));
}

function evaluate(cfg) {
  let n = 0, warn = 0, watch = 0, obs = 0, preWatch = 0, preWarn = 0, changes = 0;
  for (const id of ids) {
    const seq = dates.map((d) => ({ date: d, days: store.replay.get(d).wards[id].days }));
    const levels = [];
    for (let i = 0; i < seq.length; i++) levels.push(runSequence(seq.slice(0, i + 1), edges, cfg).state.level);
    changes += runSequence(seq, edges, cfg).transitions.length;
    for (let i = 0; i < seq.length; i++) {
      n++;
      if (levels[i] >= 2) warn++;
      if (levels[i] >= 1) watch++;
      if (i > 0 && isWarn(band(dates[i], id))) {
        obs++;
        if (levels[i - 1] >= 1) preWatch++;
        if (levels[i - 1] >= 2) preWarn++;
      }
    }
  }
  const p = (a, b) => `${((100 * a) / b).toFixed(1)}%`;
  return { warningPlus: p(warn, n), watchPlus: p(watch, n), warnedDayBefore: p(preWatch, obs), warningDayBefore: p(preWarn, obs), changesPerWard: (changes / ids.length).toFixed(1) };
}

let ow = 0, oa = 0, total = 0;
for (const d of dates) for (const id of ids) {
  total++;
  const b = band(d, id);
  if (b !== "Normal") oa++;
  if (isWarn(b)) ow++;
}

const th = store.meta.exceedance;
const rows = {
  "Observed (reference)": null,
  "First draft: F1 thresholds, D+1..2, margin 3": { ...config.hap, deescalationMargin: 3, anticipatoryLeadDays: 2, thresholds: th },
  "Thermometer: no forecast, no hysteresis": { ...config.hap, deescalationMargin: 0, minDwellDays: 1, anticipatoryLeadDays: 0, watchLeadDays: 0, thresholds: null },
  "DEFAULT (src/config.js)": { ...config.hap, thresholds: scale(th, config.hap.thresholdScale) },
};

console.log(`Replay ${dates[0]}..${dates.at(-1)}, ${ids.length} wards\n`);
console.log("| Operating point | Warning+ ward-days | Watch+ ward-days | Warning days pre-warned (Watch) | (Warning) | Level changes / ward / season |");
console.log("| --- | --- | --- | --- | --- | --- |");
for (const [name, cfg] of Object.entries(rows)) {
  if (!cfg) {
    console.log(`| ${name} | ${((100 * ow) / total).toFixed(1)}% | ${((100 * oa) / total).toFixed(1)}% | – | – | – |`);
    continue;
  }
  const r = evaluate(cfg);
  console.log(`| ${name} | ${r.warningPlus} | ${r.watchPlus} | ${r.warnedDayBefore} | ${r.warningDayBefore} | ${r.changesPerWard} |`);
}
