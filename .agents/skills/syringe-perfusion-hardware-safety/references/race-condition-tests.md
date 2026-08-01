# Race-condition test checklist

Use deterministic barriers, events, injected hooks, fake clocks, fake pumps, and fake process launchers. Do not depend on arbitrary sleeps.

## Atomic coordination

- Launch two concurrent START requests from the same ARMED revision; exactly one reserves a run and only it may reach hardware.
- Accept STOP between initial request parsing and locked transition; START must fail without commands.
- Accept STOP immediately before IN command emission; IN must not start.
- Accept STOP immediately before OUT command emission and at the IN-to-OUT deadline; OUT must not start.
- Present stale revision and stale run ID to the final gate; both must fail closed.
- Verify terminal plans cannot restart without a new successful ARM.

## Failure recovery

- Make OUT START fail after IN START; verify independent IN/OUT STOP attempts, FAULT persistence, and nonzero CLI result.
- Make one STOP fail; verify all other targets are still attempted and success is not falsely reported.
- Make detached-worker spawn fail; verify pending state and ownership rollback.
- Provide a dead-process lock and a live-process lock; recover only the dead one.
- Provide stale pending state after restart; verify no automatic hardware action.

## Recipe, legacy, GUI, and completion

- Cancel during recipe/legacy wait; verify later start blocks never execute.
- Close GUI during PENDING, STARTING, IN-to-OUT wait, recipe wait, and serial failure; verify no later START.
- Click STOP repeatedly; verify cancellation is reinforced without uncontrolled STOP workers.
- Advance completion clock after STOPPED/CANCELLED/FAULT; verify state never becomes `COMPLETED_ESTIMATED`.

Assert emitted command sequences and persisted state histories, not only returned status.
