---
name: syringe-perfusion-hardware-safety
description: Protect syringe_perfusion hardware-control invariants. Use whenever a task touches a4.py, coordinator.py, operations.py, protocol_runner.py, perfusion_state.py, recipe_engine.py, hardware CLI commands, NIS wrappers, port selection, serial I/O, pump programming, scheduling, START, cancellation, or STOP. Do not use for presentation-only work that cannot affect these paths.
---

# Hardware Safety

Apply this contract in addition to the general project workflow. Treat existing verified behavior as authoritative unless the user explicitly scopes a separately validated protocol change.

## Required inputs

- Files and execution paths affected by the request.
- Existing coordinator/state schemas, hardware fakes, race tests, and NIS wrappers.
- Active Config resolution and persisted target snapshots.

## Hardware contract

- Keep 9600 baud and 8N1 unless documented hardware specifications explicitly change.
- Keep required terminators CRLF and verified UART commands lowercase.
- Preserve commands:
  - `q1hxxd`: integer speed
  - `q2hxxd`: decimal speed
  - `q3hHHd`: hours
  - `q4hMMd`: minutes
  - `q5hSSd`: seconds
  - `q6h1d`: save
  - `q6h2d`: automatic forward
  - `q6h3d`: automatic reverse
  - `q6h4d`: manual forward
  - `q6h5d`: manual reverse
  - `q6h6d`: stop

## Safety invariants

1. After STOP or cancellation is accepted, emit no later START for that run.
2. Permit only one pending or active run per Active Config.
3. Never start OUT after cancellation, including at a delay boundary.
4. If OUT start fails, independently attempt STOP on both pumps.
5. Select emergency STOP targets from active, pending, armed, or last-known snapshots before editable configuration.
6. Let no pump's STOP failure prevent another target's STOP attempt.
7. Run no serial I/O on the Tk main thread.
8. Open no real serial port in automated tests.
9. Make DRY-RUN incapable of physical movement.
10. Treat UART completion as transmission evidence, not physical validation.
11. Describe settings as `PROGRAMMED — NOT READ BACK`.
12. Use `COMPLETED_ESTIMATED` only for elapsed programmed duration.
13. Never infer commissioning evidence from software success.
14. Prohibit live flow changes while running unless a separate validated milestone explicitly enables them.

## Review workflow

1. Trace every affected start/stop path through the shared coordinator.
2. Verify process-safe transitions re-read persisted state under the transition lock.
3. Verify run ID, state revision, cancellation generation, and final command-emission gate immediately before every START.
4. Verify all waits are monotonic, cancellable, run-aware, and perform a final deadline check.
5. Verify duplicate START rejection occurs before hardware commands.
6. Verify emergency STOP snapshot priority, deduplication, independent attempts, and failure persistence.
7. Verify GUI close records cancellation, blocks new work, stops safely, and cannot leave a delayed START.
8. Verify scheduler spawn rollback, stale-lock rules, stale-pending fail-closed behavior, and completion reconciliation.
9. Verify GUI, CLI, recipes, legacy paths, and NIS use the same Active Config and coordinator.
10. Read [references/hardware-safety-checklist.md](references/hardware-safety-checklist.md) for any implementation or audit that touches hardware paths.
11. Read [references/race-condition-tests.md](references/race-condition-tests.md) when state transitions, delays, scheduling, cancellation, or concurrency are involved.

## Verification

- Use fake pumps, injected clocks/process launchers, barriers, and events.
- Make race tests deterministic; do not rely on timing sleeps.
- Search for bypass paths, blocking `time.sleep()` in safety waits, Tk-thread serial access, duplicate STOP implementations, and unsafe wrapper configuration.
- Run focused safety tests and the complete suite.

## Output contract

State which invariants were reviewed, exact code locations, tests proving cancellation/STOP precedence, any unverified physical assumptions, and remaining P0/P1 risks. Do not claim physical movement, flow, readback, or STOP performance.
