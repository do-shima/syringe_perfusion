# NIS cmd wrappers

Preferred armed workflow:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_armed.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_armed_after_300s.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_cancel_pending.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_stop_all.cmd");
```

- `pump_start_armed.cmd`: start the already-programmed ARMED plan; no recalculation or setting write.
- `pump_start_armed_after_300s.cmd`: schedule a detached start after 300 seconds and return promptly.
- `pump_cancel_pending.cmd`: atomically cancel a pending start.
- `pump_stop_all.cmd`: cancel pending, then independently attempt STOP on all enabled pumps.
- `00_check_paths.cmd` and `pump_test_dryrun.cmd` remain available for validation.
- Legacy profile/jog wrappers are compatibility-only. `pump_start_pushpull_fast30.cmd` is deprecated and LIVE legacy `pushpull` is refused; use the armed wrappers.

All wrappers resolve ROOT from `%~dp0`, use `%ROOT%\config`, call `%ROOT%\a4ctl\a4ctl.exe`, log CONFIG/START/END/exit, redirect output, use ASCII CRLF, contain no continuation `^`, and contain no COM number or personal path.

GUI, CLI, and NIS share runtime state below `%ROOT%\config\runtime`. Do not edit `_internal\default_config`. The pump does not provide verified setting readback: use the GUI wording **PROGRAMMED — NOT READ BACK** and complete physical validation before experiments.

Tracked wrappers intentionally use `%ROOT%\config`. A custom GUI Active Config does not update them automatically; update only the local deployment CFG using GUI Setup **Copy NIS CFG line**, then run `00_check_paths.cmd`.

STOP cancellation is persisted and ordered against the final START UART-write gate. Persisted active/pending/armed target snapshots are used before editable config, and every unique STOP target is attempted independently. `COMPLETED_ESTIMATED` means programmed time elapsed without hardware readback.

Commissioning and calibration remain GUI-oriented and are intentionally not exposed through NIS wrappers. Before installing macros, use the built CLI read-only commands `preflight` and `validation-status`, then complete and archive the Setup → Commissioning workstation checklist. NIS exit codes and UART completion do not prove physical direction, delivered flow, or physical STOP.

For a validation release, record `a4ctl.exe --version`, the future tag-style version, commit, and ZIP SHA-256 before editing the workstation’s local CFG line. Standard wrappers are replaced on upgrade; keep workstation-specific wrapper changes under `nis_cmd\local` or in `*_local.cmd` files so the upgrade helper preserves them.
