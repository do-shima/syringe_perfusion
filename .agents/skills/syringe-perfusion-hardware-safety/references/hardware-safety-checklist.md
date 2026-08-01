# Hardware safety checklist

Use this checklist for implementation and audit work that can reach pumps or shared runtime state.

## Protocol and target configuration

- Confirm command strings, case, CRLF, 9600 baud, and 8N1 remain unchanged unless explicitly authorized.
- Confirm GUI, CLI, recipes, legacy operations, and NIS resolve the same Active Config.
- Confirm persisted active/pending/armed/last-known targets take priority over mutable current configuration for STOP.
- Confirm targets include role, port, serial settings, direction, identity where available, plan ID, and run ID.
- Confirm identical ports are deduplicated without suppressing a distinct target.

## State and command emission

- Reserve run IDs and transition state under an exclusive process-safe transition lock.
- Re-read persisted state under the lock; reject stale state, stale revision, stale run ID, and duplicate START.
- Release transition locks before long serial I/O.
- Check run ID, state, revision, and cancellation immediately before every START command.
- Give accepted STOP/cancellation precedence over every later command for that run.
- Never infer reusable authorization from a plan validated before lock acquisition.

## Waits and workers

- Use monotonic cancellable waits for scheduling, IN-to-OUT delay, recipes, legacy delays, and completion monitors.
- Perform a final cancellation/state check at each deadline.
- Roll back PENDING/ownership if detached worker creation fails.
- Recover only locks whose owning process is confirmed dead; never steal a live lock.
- Treat stale pending files as cancelled/faulted evidence, never as authority to start hardware.

## STOP and failures

- Record cancellation before attempting STOP I/O.
- Attempt every unique target independently, preferably concurrently.
- Continue after individual STOP failures and persist per-target outcomes.
- Persist FAULT or STOP_FAILED if any required STOP fails.
- If OUT startup fails after IN starts, immediately attempt STOP on IN and OUT independently.
- Keep emergency STOP available through invalid GUI fields, malformed current config, changed ports, changed Active Config, and GUI close.

## GUI boundaries

- Snapshot Tk values on the main thread and pass immutable data to workers.
- Never read Tk variables or update widgets from workers.
- Keep STOP outside ordinary operation guards and serialize repeated STOP workers.
- On close, cancel first, prevent new work, stop from snapshots, wait boundedly, and keep the window if STOP is unresolved.

## Evidence language

- UART completion is not movement, direction, flow, or physical STOP proof.
- Use `PROGRAMMED — NOT READ BACK` after programming.
- Use `COMPLETED_ESTIMATED` only for time-based software state.
