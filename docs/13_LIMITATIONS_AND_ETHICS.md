# Limitations and Ethics

Stated here so they are the first thing a reviewer reads, not the last thing they find.

## Scientific limitations

1. **The heat–mortality curve is transferred, not learned.** The supplied mortality (2007–11) and weather (2015–25) records share no days. Relative risk at the summer 99th percentile is set to 1.20 (range 1.10–1.35) from published tropical studies, and every mortality number carries that range.
2. **Mortality baselines come from a 2007–11 sample survey** with no heat-specific cause code, half the records lacking a day of death, uneven district coverage, and 23,269 duplicated records (removed). They supply relative structure; the absolute level is anchored to a configurable current death rate.
3. **The weather grid is ~27 km.** Ward values are interpolated and adjusted by an urban-heat-island parameterisation; they are not measurements.
4. **Ward geometry is synthetic** until real boundaries are supplied. Synthetic wards are flagged everywhere.
5. **District assignment of cells is approximate** (~9% area overshoot, small districts under-resolved).
6. **Mean radiant temperature is modelled** for an open site with one surface albedo. Street canyons, shade and wall re-radiation are not represented.
7. **HTSI weights are reasoned priors**, revised once when a validation check showed relative channels outvoting absolute heat. They have not been fitted to outcomes — they cannot be, with this data.
8. **The forecaster uses history only in replay.** Beyond two to three days its skill over climatology narrows; live mode uses numerical weather prediction instead.
9. **Intervention effect sizes** (cooling centres, work-hour shifts, advisories) are planning assumptions.
10. **Translations are drafts** pending native-speaker review.

## Ethical considerations

**Privacy.** The AHS microdata is individual-level. It never leaves the Python stage; nothing above district-month aggregation is exported, and the API serves only modelled risk. Subscriber phone numbers are masked in logs and API responses.

**Alert fatigue is a harm.** An alert that fires half the time teaches people to ignore it — the supplied notebook's method would have done exactly that. Calibration and hysteresis are safety features, not polish.

**Equity.** Vulnerability deliberately weights the elderly, the chronically ill, households without clean fuel or insurance, slum residents and outdoor workers, so resources flow toward those most at risk rather than those most able to ask. The field view and Odia-first advisories exist because the people at highest risk are least likely to open a dashboard.

**Misreading a number.** "0.4 excess deaths" in a ward is an expected value, not a prediction that someone will die there. The UI always shows ranges and labels them.

**Impersonation.** Demonstration alerts are CAP status `Exercise` and carry a neutral placeholder sender. A deployment must be operated by, and carry the identity of, the actual issuing authority.

**Automation boundary.** The system recommends and logs; people decide. HAP triggers and message dispatch are explicit operator actions behind an API key.
