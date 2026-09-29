// Heat Action Plan (HAP) state machine.
//
//   NORMAL -> WATCH -> WARNING -> EMERGENCY        (NDMA-style colour levels)
//
// Two rules make this an early-warning system rather than a thermometer:
//
// 1. It acts on the forecast. The target level for a day is the worst of
//    today's observed band and the forecast bands for D+1..D+2, and a likely
//    Warning anywhere in D+3..D+5 raises at least a Watch. Municipal
//    preparations -- opening cooling centres, rescheduling work -- take days.
//
// 2. It does not flap. Escalation is immediate; de-escalation is one level at a
//    time, only after the level has been held for `minDwellDays` AND the index
//    has stayed below the level's entry edge minus `deescalationMargin` for
//    `minDwellDays` consecutive days. A system that goes red, green, red on
//    consecutive days trains people to ignore it.
//
// Every transition carries the reason and the evidence that caused it, so the
// audit trail answers "why did we open cooling centres on the 28th?".

export const LEVELS = ["Normal", "Watch", "Warning", "Emergency"];

export const levelOf = (band) => Math.max(0, LEVELS.indexOf(band));

/**
 * Target level for one place on one issuance date.
 * @param {Array<{lead:number, htsi:number, band:string, pWarning:number}>} days D0..D5
 */
export function targetLevel(days, cfg) {
  const d0 = days[0];
  let level = levelOf(d0.band);
  let reason = `Observed ${d0.band} today (HTSI ${fmt(d0.htsi)})`;
  let trigger = { lead: 0, htsi: d0.htsi, band: d0.band };
  const th = (k) => cfg.thresholds?.[k] ?? cfg.thresholds?.[String(k)];
  const pct = (p) => `${Math.round((p ?? 0) * 100)}%`;

  // D+1..D+2: the forecast can raise today's level, either because the median
  // itself crosses a band edge or because the exceedance classifier's
  // probability clears its validated threshold. The second route is the one
  // that matters: a median forecast almost never reaches a rare extreme.
  for (let k = 1; k <= cfg.anticipatoryLeadDays && k < days.length; k++) {
    const d = days[k];
    let l = levelOf(d.band);
    let why = `Forecast ${d.band} on D+${k} (HTSI ${fmt(d.htsi)}, 80% band ${fmt(d.q10)}-${fmt(d.q90)})`;
    const t = th(k);
    if (t && (d.pWarning ?? 0) >= t.warning.threshold && l < 2) {
      l = 2;
      why = `Warning-level heat likely on D+${k}: P = ${pct(d.pWarning)} against a validated trigger of ${pct(t.warning.threshold)}`;
    } else if (t && (d.pWatch ?? 0) >= t.watch.threshold && l < 1) {
      l = 1;
      why = `Watch-level heat likely on D+${k}: P = ${pct(d.pWatch)} against a validated trigger of ${pct(t.watch.threshold)}`;
    }
    if (l > level) {
      level = l;
      reason = why;
      trigger = { lead: k, htsi: d.htsi, band: d.band, pWarning: d.pWarning, pWatch: d.pWatch };
    }
  }

  // D+3..D+5: a likely Warning raises at least a Watch -- a heads-up, never more.
  if (level < 1) {
    for (let k = cfg.anticipatoryLeadDays + 1; k <= cfg.watchLeadDays && k < days.length; k++) {
      const cut = th(k)?.warning.threshold ?? cfg.watchProbability;
      if ((days[k].pWarning ?? 0) >= cut) {
        level = 1;
        reason = `Warning-level heat possible on D+${k} (P = ${pct(days[k].pWarning)}, trigger ${pct(cut)})`;
        trigger = { lead: k, htsi: days[k].htsi, band: days[k].band, pWarning: days[k].pWarning };
        break;
      }
    }
  }
  return { level, band: LEVELS[level], reason, trigger };
}

export const initialState = (date) => ({ level: 0, since: date, belowCount: 0 });

const daysBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);

/**
 * Advance the state by one day.
 * @returns {{state:object, transition:object|null}}
 */
export function step(prev, target, htsiToday, date, edges, cfg) {
  if (target.level > prev.level) {
    return {
      state: { level: target.level, since: date, belowCount: 0 },
      transition: { date, from: LEVELS[prev.level], to: LEVELS[target.level], kind: "escalate", reason: target.reason, trigger: target.trigger },
    };
  }

  if (target.level < prev.level) {
    const entryEdge = edges[prev.level - 1];
    const clear = htsiToday != null && htsiToday < entryEdge - cfg.deescalationMargin;
    const belowCount = clear ? prev.belowCount + 1 : 0;
    const held = daysBetween(prev.since, date) >= cfg.minDwellDays;
    if (belowCount >= cfg.minDwellDays && held) {
      const to = prev.level - 1; // one level at a time
      return {
        state: { level: to, since: date, belowCount: 0 },
        transition: {
          date, from: LEVELS[prev.level], to: LEVELS[to], kind: "de-escalate",
          reason: `HTSI below ${fmt(entryEdge - cfg.deescalationMargin)} for ${belowCount} consecutive days`,
          trigger: { lead: 0, htsi: htsiToday },
        },
      };
    }
    return { state: { ...prev, belowCount }, transition: null };
  }

  return { state: { ...prev, belowCount: 0 }, transition: null };
}

/** Run a whole sequence of daily payload slices for one place. */
export function runSequence(sequence, edges, cfg) {
  let state = null;
  const transitions = [];
  let lastTarget = null;
  for (const { date, days } of sequence) {
    if (!state) state = initialState(date);
    const target = targetLevel(days, cfg);
    const { state: next, transition } = step(state, target, days[0].htsi, date, edges, cfg);
    if (transition) transitions.push(transition);
    state = next;
    lastTarget = target;
  }
  return { state, transitions, target: lastTarget };
}

function fmt(v, d = 1) {
  return v == null || Number.isNaN(v) ? "n/a" : Number(v).toFixed(d);
}
