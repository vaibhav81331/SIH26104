# Alerting and the Heat Action Plan Engine

> `server/src/alerts/`. Tested in `server/test/hap.test.js` and `alerts.test.js`.

## Levels

| HAP level | Colour + icon | HTSI entry | Meaning |
| --- | --- | --- | --- |
| Normal | grey ● | < 48.5 | routine |
| Watch | yellow ▲ | ≥ 48.5 (~top 10% of summer days) | prepare |
| Warning | orange ◆ | ≥ 59.5 (~top 3%) | act |
| Emergency | red ■ | ≥ 63.5 (~top 1%) | all measures |

Colour is never used alone: the icon and the label always accompany it.

## Deciding a level

For each ward and district, each day:

1. **Observed** — today's band sets a floor.
2. **Anticipation (D+1)** — tomorrow's forecast raises today's level when its median crosses a band edge, or when the exceedance classifier's probability clears its threshold (Warning+ → Warning, Watch+ → Watch). Opening cooling centres and moving work shifts takes a day; a warning that waits for the heat is late.
3. **Heads-up (D+2…D+5)** — a likely Warning later in the week raises at most a Watch.

## Staying stable

| Rule | Value | Why |
| --- | --- | --- |
| Escalation | immediate, may skip levels | danger does not wait |
| De-escalation | one level at a time | no whiplash from Emergency to Normal |
| Minimum dwell | 2 days at a level | a level must mean something |
| Clearance | HTSI 1 point below the level's entry edge for 2 consecutive days | an index hovering at the edge must not flap |

## Choosing the operating point — a measured trade-off

An anticipatory alert *must* fire more often than the heat itself: it warns the day before and holds through an episode. The question is how much more. Every setting below was replayed over all 332 wards for April–June 2024 (`node server/scripts/evaluate-hap.js`):

| Operating point | Warning+ ward-days | Watch+ ward-days | Observed Warning days already under a Watch the day before | …under a Warning | Level changes per ward per season |
| --- | --- | --- | --- | --- | --- |
| Observed heat (reference) | 10.7% | 38.1% | – | – | – |
| First draft: F1-optimal thresholds, D+1–D+2 escalation, 3-pt clearance | **44.8%** | 85.0% | 98.2% | 88.0% | 27.8 |
| Plain thermometer: no forecast, no hysteresis | 15.1% | 44.1% | 75.2% | **32.9%** | 39.3 |
| **Adopted** | **28.4%** | 70.6% | **94.0%** | **63.0%** | **27.1** |

The first draft was alert fatigue by construction: four times the observed rate, because classifier thresholds tuned for F1 on a *single* cell-day (~0.10 probability, precision ~0.2) were compounded over two lead days and a long hysteresis hold. A thermometer is quiet but late — two-thirds of dangerous days arrive without a Warning the day before, and it changes level most often.

The adopted point — D+1 escalation only, classifier thresholds ×2 (a precision-leaning operating point), 1-point clearance, 2-day dwell — cuts alert days by 37% against the draft, still has 94% of dangerous days under at least a Watch the day before, and is the most stable of the three. April–June 2024 was an unusually hot season, so these rates are a severe case; the burden in a milder season has not been measured here. Every parameter is an environment variable (`USHMA_HAP_*`), so an authority can choose its own point on this curve and re-run the evaluation.

## Advisories

Seven audiences × three levels × three languages, in `i18n/{en,hi,or}.json` so they can be corrected by fluent speakers without touching code. Odia and Hindi are marked **draft, pending native-speaker review**. Odia text uses Odia numerals.

| Audience | Example Warning actions |
| --- | --- |
| Public | stay indoors 11–4; water every 30 min; ORS |
| Elderly | medicines out of heat; daily check-in; sponge cooling |
| Outdoor workers | heavy work before 11 / after 4; 15 min shade per hour |
| Schools | end classes before 11; no outdoor activity |
| Hospitals | heat-illness triage; cooling beds; expected ED surge figure |
| Power utility | evening peak preparation; priority supply to hospitals and cooling centres |
| Municipal | open cooling centres; water tankers; construction hours |

The emergency number in every advisory is **108**.

## CAP 1.2

`GET /v1/alerts/:id/cap.xml` returns an OASIS CAP 1.2 alert with one `<info>` block per language, severity (Moderate/Severe/Extreme), urgency (Immediate/Expected/Future by lead), certainty (Observed/Likely/Possible by probability), response type, HTSI/MRI/WBGT parameters and the ward polygon. Replay alerts are `status=Exercise` with an explanatory note; live alerts are `Actual`. The default sender is a neutral placeholder — a deployment sets the issuing authority's own identity.

## Delivery

Subscribers choose channel, area (wards, districts or cities), language, audience and minimum level. Each alert is sent to each subscriber once. SMS uses the short text; WhatsApp adds the action list. Webhooks receive the full JSON, HMAC-signed.

## Heat Action Plan triggers

`POST /v1/hap/trigger` records a decision with its per-agency action plan (municipal, hospitals, power utility, schools). The Command page shows the municipal checklist; each item acknowledged is logged with who and when.
