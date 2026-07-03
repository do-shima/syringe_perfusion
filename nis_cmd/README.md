# NIS cmd wrappers

This directory documents the `.cmd` wrappers used by NIS-Elements 6.02.

The wrappers are intentionally simple:

- Each wrapper calls `a4ctl.exe`.
- Each wrapper passes `--config-dir` explicitly.
- Each wrapper writes execution information to `nis_logs\nis_exec.log`.
- The wrappers should not depend on the NIS current directory.
- Current `.cmd` files should be ASCII, CRLF, and no BOM.

Expected Nikon PC root:

```text
D:\data\Do\Syringe_pump
```

Expected wrapper directory:

```text
D:\data\Do\Syringe_pump\nis_cmd
```

Run order and purpose:

- `00_check_paths.cmd`: run first after copying files or changing ROOT.
- `pump_list_ports.cmd`: list visible COM ports.
- `pump_test_dryrun.cmd`: verify command path and config path without moving the pump.
- `pump_write_fast30.cmd`: write Fast-30 speed/time before acquisition.
- `pump_start_fast30.cmd`: start the saved Fast-30 profile from the NIS acquisition trigger.
- `pump_start_fast30_async.cmd`: use only when NIS blocks or delays imaging and asynchronous launch is required.
- `pump_start_fast30_worker.cmd`: worker used by the async wrapper.
- `pump_stop_all.cmd`: safety stop for enabled pumps.
- `pump_jog_forward_500ms.cmd`: short forward jog for safe setup checks.
- `pump_jog_forward_500ms_dryrun.cmd`: dry-run version of the 500 ms jog.
- `pump_start_after_30s_recipe.cmd`: run the delayed recipe when a recipe-side wait is required.

During experiments, avoid editing these files except for the deployment `ROOT` path. COM port changes should be made in `config\pumps.json`, not by hard-coding COM values in wrapper files.

Logging is intentionally split:

- `nis_logs\nis_exec.log` is written by `.cmd` wrappers.
- `logs\a4pump_YYYYMMDD.csv` is written by `a4ctl.exe` and `A4PumpGUI.exe`.

Log unification is future work.
