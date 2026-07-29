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
- `00_check_paths.cmd`, `pump_test_dryrun.cmd`, and legacy profile/jog wrappers remain available.

All wrappers resolve ROOT from `%~dp0`, use `%ROOT%\config`, call `%ROOT%\a4ctl\a4ctl.exe`, log CONFIG/START/END/exit, redirect output, use ASCII CRLF, contain no continuation `^`, and contain no COM number or personal path.

GUI, CLI, and NIS share runtime state below `%ROOT%\config\runtime`. Do not edit `_internal\default_config`. The pump does not provide verified setting readback: use the GUI wording **PROGRAMMED — NOT READ BACK** and complete physical validation before experiments.
