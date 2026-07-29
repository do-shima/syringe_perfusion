# NIS-Elements 6.02 armed perfusion integration

## Preferred workflow

NIS starts a plan that the GUI has already calculated, programmed, and atomically armed. NIS does not recalculate flow and does not rewrite q1/q2/q3/q4/q5/q6h1 settings.

1. Start GUI and scan serial ports.
2. Select independent IN and OUT ports and test each.
3. Choose Fixed volume, Fixed duration, or bounded continuous flow.
4. Review programmed speed/duration and exact UART commands.
5. Switch from DRY-RUN to LIVE.
6. Select **PROGRAM / ARM BOTH**.
7. Confirm **PROGRAMMED — NOT READ BACK**.
8. Start NIS acquisition.
9. Trigger an immediate or delayed armed wrapper.
10. Use STOP ALL for cancellation or emergency stop.

The A4 has no verified speed/time readback. PROGRAMMED means the write sequence completed without an I/O exception; it is not independent device verification.

## Shared state and config

Every wrapper resolves:

```bat
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "A4=%ROOT%\a4ctl\a4ctl.exe"
set "CFG=%ROOT%\config"
```

GUI, CLI, and NIS share the four JSON config files and:

```text
<CFG>\runtime\perfusion_state.json
<CFG>\runtime\pending_run.json
<CFG>\runtime\run.lock
<CFG>\runtime\protocol_runner.log
```

Do not edit `_internal\default_config`; it is only an initial copy source. COM names are environment-specific and belong in the external `pumps.json`, never in tracked wrappers.

## NIS macros

Immediate start:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_armed.cmd");
```

Start after 300 seconds:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_armed_after_300s.cmd");
```

The delayed wrapper calls `schedule-armed --delay-s 300`. The CLI starts a detached worker and returns promptly; NIS is not kept in a five-minute blocking call.

Cancel pending:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_cancel_pending.cmd");
```

Cancel pending and stop both:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_stop_all.cmd");
```

STOP ALL updates shared cancellation state before sending STOP. A waiting worker checks its unique run ID and exits without starting if the plan was changed or cancelled. Cancellation during IN-to-OUT delay stops IN and prevents OUT start.

## Validation and failure behavior

Before start, the CLI checks:

- state is exactly ARMED (or the matching scheduled PENDING run);
- config fingerprint still matches;
- IN and OUT remain enabled on different ports;
- both selected ports are currently detected;
- HWID matches when both stored and current values are available;
- no duplicate run lock exists.

OUT start failure after IN start triggers STOP attempts for both and records FAULT. Slider movement never sends UART commands. Speed is not changed after STARTED.

Inspect:

```powershell
<A4PUMP_ROOT>\a4ctl\a4ctl.exe --config-dir "<A4PUMP_ROOT>\config" arm-status
```

Wrapper START/END/config/exit logs are in `nis_logs\nis_exec.log`; protocol state transitions are in `config\runtime\protocol_runner.log`.

## Wrapper format

Tracked `.cmd` files are ASCII/CRLF, contain no continuation `^`, use one a4ctl command per line, and contain no personal paths or COM numbers. Legacy profile wrappers remain for compatibility, but the armed workflow is preferred.

## Hardware checks still required

Automated tests do not open a real serial port. Validate pump directions, water-weight flow, simultaneous liquid level, STOP behavior, delayed cancellation, actual NIS `Int_ExecProgram`, and Windows 125%/150% scaling on the microscope PC.
