# Calibration evidence

## Measurement record

For each replicate record pump role/direction, syringe, requested flow, programmed speed/duration/travel, expected volume, measured volume, measured flow, errors, candidate `ul_per_mm`, operator, timestamp, method, density when gravimetric, note, and artifact/validation identity.

## Calculations

- `candidate_ul_per_mm = measured_volume_ul / programmed_travel_mm`
- `measured_flow_ml_min = measured_volume_ul / programmed_duration_min / 1000`
- Reject zero/invalid travel, duration, density, and impossible measurements.
- Preserve every replicate. Exclude one only with an explicit recorded reason.
- Report accepted `n`, mean, sample standard deviation, coefficient of variation, median, min, max, mean percent error, and candidate calibration.

## Acceptance

- Treat configured thresholds as workflow policy, not universal scientific law.
- Record thresholds with the result.
- Require manual/measured evidence; UART completion is insufficient.
- Do not automatically update syringe calibration.
- Before applying a candidate, show old/new values, replicate evidence, affected preset, and armed-plan invalidation.
- Preserve unknown JSON keys, back up, write atomically, record method/date/validation ID, and invalidate armed state.
- Record OUT reverse evidence direction-specifically; do not apply it as general geometry correction in the current milestone.

## Balance

Record expected/measured IN and OUT volumes, net balance/error, fluid path, priming, bubbles, leakage, chamber/tubing, fluid, duration, and operator observations. Do not claim liquid-level stability without measurement or explicit observation.
