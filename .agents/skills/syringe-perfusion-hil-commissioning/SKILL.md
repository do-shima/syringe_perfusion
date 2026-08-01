---
name: syringe-perfusion-hil-commissioning
description: Guide fixed-build hardware-in-the-loop commissioning for syringe_perfusion. Use for physical pump direction checks, emergency STOP tests, delayed-cancellation rehearsal, gravimetric or volumetric flow measurement, IN/OUT balance, NIS-Elements integration, and microscope-workstation validation. Do not use for automated software-only verification or source modification during a validation session.
---

# HIL Commissioning

Run a controlled, traceable validation session against one immutable artifact. Compose with hardware-safety and review-closeout.

## Required inputs

- Versioned artifact, SHA-256, build identity, Active Config, operator, workstation, pump/adapter identities, syringe, tubing/chamber, fluid, and approved test plan.
- Immediate access to software STOP ALL and physical power isolation.

## Evidence contract

Classify every result as one of:

- SOFTWARE CHECK
- UART COMMAND COMPLETED
- MANUAL PHYSICAL CONFIRMATION
- MEASURED RESULT
- NOT VALIDATED
- STALE
- FAILED

Never infer movement, direction, delivered flow, or physical STOP latency from UART success or software timestamps. Use `PROGRAMMED — NOT READ BACK` and `COMPLETED_ESTIMATED` accurately.

## Non-negotiable session guardrails

- Verify artifact identity and checksum before testing.
- Use only bounded operations and safe test fluid before cells.
- Keep STOP ALL and power isolation immediately reachable.
- Stop at the first safety-critical failure and follow [references/hil-stop-rules.md](references/hil-stop-rules.md).
- Export diagnostics before modifying software.
- Do not modify source during the fixed-build session. A fix requires a new build identity and a new session.
- Record operator, timestamps, evidence type, observations, measurements, deviations, and artifact identity.

## Required stages

1. Artifact identity and checksum.
2. Installation and Active Config.
3. IN/OUT adapter identity without inferring roles from COM numbers.
4. Bounded IN direction confirmation.
5. Bounded OUT direction confirmation.
6. STOP IN.
7. STOP OUT.
8. STOP both.
9. Delayed-cancellation rehearsal, DRY-RUN first.
10. IN flow measurement.
11. OUT reverse measurement.
12. Paired IN/OUT balance.
13. Actual microscope fluid path.
14. NIS integration.
15. Display scaling and constrained geometry.
16. Evidence and diagnostics export.
17. Final disposition.

For calibration evidence and exclusions, read [references/calibration-evidence.md](references/calibration-evidence.md). Use [templates/hil-session.md](templates/hil-session.md) for the session record and [templates/defect-report.md](templates/defect-report.md) at each defect.

## Verification and stopping conditions

- Confirm every movement has a programmed bound and a STOP path.
- Record software-observed timestamps separately from manual observation.
- Attempt STOP independently on every target if a failure occurs.
- Mark the session FAILED or INCOMPLETE when required physical evidence is absent.

## Output contract

Report artifact identity, completed stages, evidence by level, deviations/defects, exported files, checks not performed, and a bounded disposition. Never state “hardware validated” unless every required physical observation or measurement is present and current.
