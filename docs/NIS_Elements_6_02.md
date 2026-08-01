# NIS-Elements 6.02 armed perfusion integration

## Preferred workflow

NIS starts a plan that the GUI has already calculated, programmed, and atomically armed. NIS does not recalculate flow and does not rewrite q1/q2/q3/q4/q5/q6h1 settings.

1. Start GUI and wait for the background daily serial-port scan.
2. Review and explicitly lock the independent IN and OUT adapter assignments in **Daily Setup / 本日の接続**. A current successful scan and identity-consistent lock are required before GUI LIVE programming or start.
3. Choose Fixed volume, Fixed duration, or bounded continuous flow.
4. Review programmed speed/duration and exact UART commands.
5. Switch from DRY-RUN to LIVE.
6. Select **PROGRAM / ARM BOTH**.
7. Confirm **PROGRAMMED — NOT READ BACK**.
8. Start NIS acquisition.

The daily assignment review is a GUI LIVE prerequisite and does not change wrapper semantics: NIS still reads the same external `pumps.json`. Scanning and connection checks never send movement commands. A date change, USB-topology change, identity conflict, unlock, or confirmed reassignment requires review and reprogramming in the GUI before the next LIVE session.

Before production use, open Setup → Commissioning and complete the applicable adapter identity, direction, STOP, cancellation, flow, balance, and workstation checks. Run:

```text
<A4PUMP_ROOT>\a4ctl\a4ctl.exe --config-dir "<A4PUMP_ROOT>\config" preflight
<A4PUMP_ROOT>\a4ctl\a4ctl.exe --config-dir "<A4PUMP_ROOT>\config" validation-status
```

These inspection commands do not move pumps. A UART command exit code is software evidence only; actual NIS `Int_ExecProgram`, physical motion, flow, and display appearance require manual observation.
Record `a4ctl.exe --version` and the release ZIP SHA-256 on the validation-session cover sheet before running NIS commissioning.
9. Trigger an immediate or delayed armed wrapper.
10. Use STOP ALL for cancellation or emergency stop.

The A4 has no verified speed/time readback. PROGRAMMED means the write sequence completed without an I/O exception; it is not independent device verification.

`COMPLETED_ESTIMATED` means only that the persisted programmed duration elapsed while the same run remained STARTED. It is not device readback and does not prove that either pump moved.

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

Tracked wrappers explicitly use `%ROOT%\config`. A GUI-selected custom Active Config does not rewrite them automatically. Use Setup **Copy NIS CFG line** in the local deployment copy when a nonstandard config directory is required, and verify `a4ctl.exe --config-dir "<CFG>" config-path` before acquisition.

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

STOP ALL is ordered against the final UART START-write gate, persists a new cancellation generation, and then attempts every unique persisted target independently. A waiting worker checks its run ID, operation ID, state revision, and cancellation generation, including a final check after each deadline. Once STOP has been accepted for a run, that run cannot emit a later START. Cancellation during the global or IN-to-OUT delay prevents the later START; if IN already started, persisted targets are used for STOP even when current `pumps.json` is missing, malformed, disabled, or edited.

## Validation and failure behavior

Before start, the CLI checks:

- state is exactly ARMED (or the matching scheduled PENDING run);
- config fingerprint still matches;
- IN and OUT remain enabled on different ports;
- both selected ports are currently detected;
- HWID matches when both stored and current values are available;
- no duplicate run lock exists.

The transition lock is short-lived and re-reads persisted state before reservation. A separate command-emission gate covers only final authorization and UART write/flush, so two concurrent START requests cannot reuse one prior ARMED validation.

OUT start failure after IN start triggers STOP attempts for both and records FAULT. Slider movement never sends UART commands. Speed is not changed after STARTED.

GUI **GUI START delay sec** uses the same detached scheduler when greater than zero; zero starts immediately. CLI `start-armed` remains explicitly immediate, while CLI delay is always `schedule-armed --delay-s N`.

Inspect:

```powershell
<A4PUMP_ROOT>\a4ctl\a4ctl.exe --config-dir "<A4PUMP_ROOT>\config" arm-status
```

Wrapper START/END/config/exit logs are in `nis_logs\nis_exec.log`; protocol state transitions are in `config\runtime\protocol_runner.log`.

## Wrapper format

Tracked `.cmd` files are ASCII/CRLF, contain no continuation `^`, use one a4ctl command per line, and contain no personal paths or COM numbers. `pump_start_pushpull_fast30.cmd` is deprecated and LIVE `pushpull` is refused; DRY-RUN diagnostics remain. Other legacy profile wrappers are compatibility-only and new macros must use the armed workflow.

## Hardware checks still required

Automated tests do not open a real serial port. Validate pump directions, water-weight flow, simultaneous liquid level, STOP behavior, delayed cancellation, actual NIS `Int_ExecProgram`, and Windows 125%/150% scaling on the microscope PC.

Record the workstation checklist in Setup → Commissioning and archive the JSON/CSV/Markdown report. The report remains `SOFTWARE READY — HARDWARE VALIDATION INCOMPLETE`, `COMMISSIONING PARTIAL`, `FAILED`, or `STALE` until the corresponding physical/manual or measured evidence is entered.

For support, run the read-only `diagnostics-summary` or `export-diagnostics --output "<PATH>.zip"` commands. Port enumeration does not open a serial connection, and diagnostics never invokes an NIS macro.
