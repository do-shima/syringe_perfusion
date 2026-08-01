# HIL stop rules

## Before movement

- Identify the exact artifact, Active Config, target adapter, pump role, direction, flow/speed, maximum duration, expected volume, and operator.
- Confirm global STOP ALL and physical power isolation are immediately reachable.
- Use a bounded conservative setting and safe fluid.
- Confirm the operator understands that commands are not read back.

## During a STOP test

- Record START authorization/write/completion timestamps separately.
- Record STOP request/write/completion timestamps separately.
- Ask for explicit manual observation of physical stopping.
- Do not label software command latency as motor-stop latency.
- Test IN, OUT, and both as separate evidence items.

## Immediate abort conditions

- Unexpected direction, unbounded movement, leakage, obstruction, loss of fluid containment, inability to reach STOP/power, unexpected start after cancellation, or any STOP UART failure.
- On abort: request cancellation, attempt every target STOP independently, isolate physical power if movement persists, record the exact evidence, and end the session.
- Keep the application visible on unresolved STOP failure and display manual emergency instructions.

No subsequent validation stage may resume until the safety failure is understood, corrected in a new build/config where required, and the session is restarted from artifact identity.
