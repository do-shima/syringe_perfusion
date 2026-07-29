# NIS cmd wrappers

These wrappers use the single Active Config at `<A4PUMP_ROOT>\config`. Every wrapper resolves ROOT from its own location, sets `CFG=%ROOT%\config`, logs that path, and passes `--config-dir "%CFG%"` to `a4ctl.exe`.

Primary NIS macros:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_write_in_out.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_pushpull_fast30.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_stop_all.cmd");
```

Available wrappers:

- `00_check_paths.cmd`: validate executable and all four JSON files; log `config-path`.
- `pump_test_dryrun.cmd`: dry-run STOP ALL without opening serial ports.
- `pump_list_ports.cmd`: record detected ports.
- `pump_write_in_out.cmd`: write IN then OUT profiles; OUT is skipped if IN fails.
- `pump_start_pushpull_fast30.cmd`: start the coordinated push-pull mode.
- `pump_stop_all.cmd`: stop all enabled pumps.
- `pump_write_fast30.cmd`, `pump_start_fast30.cmd`: IN-only compatibility operations.
- `pump_jog_forward_500ms.cmd` and `_dryrun.cmd`: bounded setup jog.

Tracked wrappers are ASCII/CRLF, contain no `^` continuation, use one a4ctl command per line, and contain neither personal paths nor COM numbers. Configure COM ports in the shared `config\pumps.json` through GUI Setup.
