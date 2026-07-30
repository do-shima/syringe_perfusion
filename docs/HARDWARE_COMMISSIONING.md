# Hardware Commissioning Guide

This guide makes controlled bench validation reproducible. It does not claim that any pump, tubing path, microscope, or NIS workstation has been physically validated.

## Evidence levels

- **SOFTWARE CHECK**: configuration, state, timing, path, or cancellation logic was evaluated.
- **UART COMMAND COMPLETED**: bytes were written without a reported serial exception. This is not hardware readback.
- **MANUAL PHYSICAL CONFIRMATION**: a named operator recorded an observation.
- **MEASURED RESULT**: entered volume or mass data was evaluated against recorded criteria.
- **NOT VALIDATED / STALE / FAILED**: evidence is absent, no longer matches its dependencies, or failed.

The A4 protocol has no verified settings or motion readback. Interpret **PROGRAMMED — NOT READ BACK** literally. `COMPLETED_ESTIMATED` means only that programmed time elapsed while the same persisted run remained STARTED.

## Storage and audit trail

Commissioning files are created only beneath the shared Active Config:

```text
<ACTIVE_CONFIG>\validation\
  commissioning_state.json
  measurements.csv
  validation_events.jsonl
  history\
  reports\
```

They are not required by `load_config()`, not packaged as writable defaults, and not committed. Current JSON state uses UTF-8 atomic replacement. Events and measurements use process-safe append locking. Reports are available as JSON, CSV, and Markdown.

Every record identifies the operator, application/build, Active Config and fingerprint, COM/identity metadata, serial settings, syringe calibration, tests, measurements, confirmations, failures, acknowledgements, and stale reasons. Do not store secrets.

## Recommended commissioning sequence

1. Install the Windows one-folder build.
2. Confirm the Active Config.
3. Scan ports.
4. Confirm IN and OUT adapter identity.
5. Test port opening.
6. Validate IN forward direction.
7. Validate OUT reverse direction.
8. Validate STOP separately and together.
9. Rehearse delayed cancellation.
10. Measure IN forward flow.
11. Measure OUT reverse flow.
12. Apply syringe calibration only after reviewing replicates.
13. Validate IN/OUT balance.
14. Validate NIS wrappers on the microscope PC.
15. Export and archive the commissioning report.
16. Enable strict production commissioning policy where appropriate.

## Port identity

The Commissioning page displays device, description, HWID, manufacturer, product, serial number, VID, PID, and location when supplied by the OS. Physically confirm each adapter role. COM numbers never imply IN or OUT.

If a stable serial/HWID appears on a different COM port, the UI presents it only as a probable match. An operator must explicitly confirm before `pumps.json` changes. Conflicting stable identity makes validation stale and can block preflight.

## Direction and STOP

Direction checks are bounded to 100–5000 ms, defaulting to 750 ms:

- IN: expected forward delivery.
- OUT: expected reverse withdrawal.

The coordinator reserves a run ID and target snapshot, the final command gate protects motion, and independent STOP attempts run at the bound or cancellation. UART success leaves the result **AWAITING MANUAL CONFIRMATION**. Record correct, incorrect, no movement, or uncertain. Incorrect direction is FAILED and blocks production readiness; the software does not silently reverse the scientific role.

STOP checks can be run for IN, OUT, and both. Records distinguish start command time, persisted STOP request, STOP UART result timestamps, and command completion. These are software-observed command timings, not measured motor-stop latency. Confirm physical stopping manually. If STOP UART fails, keep the application open and use the laboratory’s physical emergency procedure.

## Cancellation rehearsal

The default rehearsal is DRY-RUN. It uses a unique coordinator rehearsal run with a bounded delay and no permission to create a production ARMED plan or emit START. Cancel near the deadline and review:

- scheduled and cancellation times;
- IN/OUT authorization (both must remain false);
- final STOPPED/CANCELLED state;
- no later STARTED transition.

Optional physical rehearsal should be attempted only after direction and STOP validation and must remain bounded.

## Flow measurement and calibration

Standard templates are 0.5, 1.0, 2.0, and 3.0 mL/min. Each point is checked against existing device speed limits for the selected syringe; unsupported points are refused. Custom points are allowed.

For direct volume, enter µL or mL. For gravimetric measurement, enter initial/final mass, unit, and an editable liquid density in g/mL. The displayed approximate density is not an unquestioned temperature-specific constant; record the actual method and density used.

For each replicate:

```text
programmed_travel_mm = programmed_speed_mm_min × programmed_duration_s / 60
candidate_ul_per_mm = measured_volume_ul / programmed_travel_mm
measured_flow_ml_min = measured_volume_ul / (programmed_duration_s / 60) / 1000
```

Zero/invalid travel and density are rejected. Replicates are never silently discarded. Exclusion requires a recorded reason.

Accepted replicates report n, mean, sample standard deviation, coefficient of variation, median, min, max, mean flow error, and candidate calibration. Workflow defaults are at least 3 accepted replicates, CV no greater than 5%, and absolute mean flow error no greater than 5%. These are editable workflow criteria, not universal scientific laws.

The software separately tracks IN forward and OUT reverse evidence at 0.5/1.0/2.0/3.0 mL/min. Displacement conversion, operating-range validation, OUT reverse performance, and paired balance are distinct conclusions.

### Applying a candidate

Calibration is never applied automatically. **Apply candidate calibration to syringe preset** shows the old and candidate values, replicate count, CV, flow error, and syringe key. After confirmation it:

- creates `syringes.json.bak`;
- atomically updates `syringes.json` while preserving unknown keys;
- records date, method, validation ID, and statistics;
- invalidates ARMED/PENDING under the shared transition lock;
- marks dependent commissioning evidence stale.

OUT reverse evidence is not automatically converted into a general syringe-geometry correction.

## Paired IN/OUT balance

Record requested IN/OUT flow (including ratios such as 0.90, 1.00, or 1.10), duration, measured collected volumes, optional starting/ending dish volume or mass, tubing, chamber, syringe, fluid, priming, bubbles, leakage, and notes.

The report calculates expected and measured IN/OUT volumes, expected/measured net balance, balance error, and estimated dish change. It never asserts liquid-level stability without measured or explicit manual evidence.

## NIS/workstation checklist

Manually review:

- built GUI startup;
- built CLI Active Config;
- wrapper ROOT and CFG;
- immediate, delayed, cancel-pending, and STOP wrappers;
- NIS `Int_ExecProgram` result;
- 100%, 125%, and 150% Windows scaling;
- 900×600 constrained layout.

Software can verify paths and exit codes. Actual NIS execution and display appearance require operator confirmation. Screenshots are optional and stored only when explicitly selected.

## Staleness and production policy

Relevant evidence becomes STALE when dependent COM/HWID, baudrate, terminator, timeout, syringe key/calibration, direction assignment, relevant config fingerprint, or materially relevant application version changes. Unrelated UI display preferences do not invalidate evidence. Previous records remain in history.

Preflight classifications:

- **BLOCK**: invalid/missing/duplicate ports, HWID conflict, unsafe runtime, unresolved FAULT/STOP_FAILED, invalid ARMED fingerprint/duration, live transition lock, or failed physical direction/STOP.
- **WARN**: missing/stale commissioning, flow/reverse-flow/balance/workstation evidence, or unstable identity metadata.
- **INFO**: DRY-RUN, OUT disabled, custom Active Config, slider-range display mismatch, and no hardware readback.
- **PASS**: no software BLOCK finding.

Existing installations default to warnings plus an explicit, named, reasoned per-session acknowledgement for LIVE Experiment START. The optional local preference **Require current commissioning for LIVE armed start** blocks until required commissioning is current. Neither acknowledgements nor any expert process can override software BLOCK conditions.

## Dashboard and read-only CLI

The Experiment Dashboard shows state, plan/run IDs, ports/detection, IN/OUT flow and ratio, programmed duration/expected volumes, scheduled/software start and expected end, estimated countdowns, commissioning, preflight, last fault, and STOP status. Countdown display is informational and never sends UART.

Read-only commands:

```text
a4ctl.exe --config-dir "<CFG>" preflight [--json] [--require-commissioned]
a4ctl.exe --config-dir "<CFG>" validation-status [--json]
a4ctl.exe --config-dir "<CFG>" export-validation --format json|csv|markdown --output "<PATH>"
a4ctl.exe --config-dir "<CFG>" recent-runs --limit 20 [--json]
```

Recent history is derived from existing command and state-transition logs, newest first. It can be filtered and exported without deleting source history.

## Remaining manual responsibility

Automated tests and build smoke checks do not validate physical motion, delivered flow, motor-stop latency, tubing behavior, balance, NIS execution, or microscope display usability. Perform these checks with safe fluid paths, conservative limits, a visible global STOP, and the laboratory’s physical emergency procedure.
