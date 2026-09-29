# Dashboard

React 18 + Vite + Leaflet + Recharts, in `dashboard/`. Built to `dashboard/dist` and served by the Node server.

## Screens

**Map** — the operational view.
- Layers: *Heat band* (HTSI), *Mortality risk* (MRI), *Excess deaths per 100,000 per day*, *Vulnerability*. Excess deaths are shown as a rate: a count on a choropleth maps population, not risk.
- 0.25° grid cells (native model resolution), ward polygons, and district markers coloured by their HAP level.
- Lead slider D+0…D+5; zoom-to-city.
- Side panel with no selection: statewide attributable deaths (with range), wards and districts at Warning+, the ranked list of wards under a Heat Action Plan.
- Ward panel: HAP level and the reason for it; HTSI, MRI, excess deaths with range, WBGT, night WBGT, UHI contribution; observed-plus-forecast chart with the calibrated 80% band; plain-language "why" (SHAP drivers, UHI, risk arithmetic); five-day table; demographics; advisory in any language and audience; trigger HAP; CAP XML; field view.

**Command** — alerts table by ward or district, selected alert with reason, municipal checklist with acknowledgement, CAP link, level-change history, live event feed and audit trail, subscriber management, "Evaluate & dispatch", delivery log.

**Cooling centres** — choose a city, number of centres and walking radius; toggle work-hour shift and targeted advisories. Shows recommended sites in priority order on the map with their coverage circles, share of risk covered, forecast deaths and deaths averted (both with range), and the assumptions used.

**Evidence** — the validation story: supplied notebook vs USHMA alert rates, monthly comparison with the temperature rule, forecast error by lead against persistence and climatology, band coverage before and after conformal calibration, Warning-day F1, reliability diagram, SHAP importance, annual attributable deaths with NCRB, deaths by month, and what the system cannot know.

**Field view** (`/field`) — for ASHA and anganwadi workers: pick a ward, see today's level as a large coloured card with icon, tomorrow and the peak day, three actions, a copyable SMS. Odia by default. Installable PWA; the service worker keeps the app shell and the last advisory available offline.

## Top bar

Mode badge (Replay / Live), as-of date with previous/next and **Play** (advances a day every 1.6 s — watch alerts escalate across the state), **Go live** (fetches today's forecast), and the operator key for write actions.

## Colour and accessibility

| Encoding | Palette role | Values |
| --- | --- | --- |
| HAP / HTSI band | status palette + icon + label | grey ●, yellow ▲ `#fab219`, orange ◆ `#ec835a`, red ■ `#d03b3b` |
| MRI, excess rate, vulnerability | single-hue sequential ramp | blue `#cde2fb` → `#0d366b` |
| Comparisons (≤ 3 series) | categorical slots 1–3 | blue, orange, aqua |

The categorical palette was run through the colour-vision validator in both light and dark modes, all-pairs (worst CVD ΔE 9.2 light / 9.4 dark). Aqua sits below 3:1 contrast on the light surface, so every chart that uses it carries direct labels and a **Table** toggle. Dark mode has its own validated steps. Keyboard focus is visible, reduced-motion is respected, and every chart has a data table.
