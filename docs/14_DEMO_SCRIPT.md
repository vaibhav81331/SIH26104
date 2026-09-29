# Demo Script — 5 minutes

Start the server (`cd server && npm start`), open `http://127.0.0.1:8787`. It opens in replay on **29 May 2024**.

---

## 0:00 — The problem (30 s)

> "India warns on air temperature. People die of heat stress — temperature, humidity, wind and sun together, day *and night*. We forecast what the weather does to the body."

Open **Evidence**. Point at the first tiles:

- *Supplied notebook: 49.7% of days flagged Red.* "It paired the day's maximum temperature with the day's mean humidity — an hour that never happened. An alarm that rings half the time isn't an alarm."
- *USHMA: 3.0% of summer days at Warning or above.*

## 0:30 — What a temperature rule cannot see (45 s)

Stay on **Evidence**, first chart.

- "In July and August the temperature rule fires **zero** times. We fire 977 times, because WBGT sits above the survivability limit under monsoon humidity."
- "Half our alerts are days a 40 °C rule misses — mean air temperature 36 °C, mean WBGT 36.4 °C."

## 1:15 — The map (60 s)

Open **Map**.

- "234 grid cells at the model's native 27 km, 30 districts, 332 wards." Switch layers: *Heat band → Mortality risk → Excess deaths per 100k → Vulnerability.*
- Drag **Lead** to D+3. "This is a forecast, with calibrated uncertainty — the 80% band covers 79% of outcomes on years the model never saw."
- Press **Play**. Watch western Odisha — Balangir, Sambalpur, Bargarh — go red as the clock reaches **1 June 2024**: 62 wards at Emergency, ~38 heat-attributable deaths a day statewide. Press **Pause**.

## 2:15 — One ward, fully explained (60 s)

Click the top ward in the side list.

- "Why is it Emergency?" — read the reason line. "Every level states what triggered it."
- Chart: observed stress, then the forecast with its band.
- **Why**: "today's peak UTCI adds 10 points… urban heat adds 2.4… and the risk arithmetic — baseline deaths × relative risk × vulnerability — is on screen. No black box between heat and deaths."
- **Advisory**: switch to **ଓଡ଼ିଆ**, audience *elderly*. "Seven audiences, three languages."
- Click **CAP 1.2 XML**. "The international alerting standard, one block per language — status *Exercise* because this is a replay."

## 3:15 — Decisions, not just dashboards (45 s)

Open **Cooling centres**, Bhubaneswar, 8 centres.

- "Where do I open eight cooling centres tomorrow?" Numbered sites appear. "They cover 43% of the forecast risk; with work-hour shifts and targeted SMS, about 0.7 deaths averted over three days — with its range. The effect sizes are stated planning assumptions."

## 4:00 — Operations and the last mile (40 s)

Open **Command**: alerts with reason and since-date, the Heat Action Plan checklist, subscribers, **Evaluate & dispatch** → the delivery log fills (simulated: nothing leaves the machine).

Open **Field view** on a phone-sized window: "An ASHA worker sees one ward, today's level, three actions in Odia, and an SMS to forward. It works offline."

## 4:40 — Honesty (20 s)

> "Four things we found in the supplied data and fixed: the notebook's impossible humidity pairing; mortality and weather that share no years — so our AI forecasts heat stress and deaths come from a transparent, labelled curve; 23,269 duplicated death records; and vulnerability columns identical for every district. We also caught our own first alert settings firing four times too often, measured it, and fixed it. It's all in the docs."

---

## Backup answers

| If asked | Answer | Where |
| --- | --- | --- |
| "Where is the AI?" | LightGBM forecaster, 40 models, trained on the mandated hourly data; beats persistence and climatology at every lead | `docs/10_MODEL_CARD.md` |
| "Why not predict deaths directly?" | No overlapping years between mortality and weather — any such model is leaked or impossible | `docs/05` |
| "How good is it on dangerous days?" | Warning+ AUC 0.93 at D+1, F1 0.26 vs persistence 0.18; modest because these days are 1% of the record | `docs/11` |
| "Won't people ignore it?" | The operating point was chosen on measured alert burden vs anticipation; 94% of dangerous days pre-warned | `docs/09` |
| "Are the wards real?" | Synthetic until real boundaries are supplied — flagged everywhere; drop a GeoJSON and rebuild | `docs/06` |
| "Is it live?" | **Go live** runs today's Open-Meteo forecast through the identical pipeline | `docs/01` |
