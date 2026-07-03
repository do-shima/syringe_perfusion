# NIS cmd wrappers

This directory documents the `.cmd` wrappers used by NIS-Elements 6.02.

The wrappers are intentionally simple:

- Each wrapper calls `a4ctl.exe`.
- Each wrapper passes `--config-dir` explicitly.
- Each wrapper writes execution information to `nis_logs\nis_exec.log`.
- The wrappers should not depend on the NIS current directory.
- Current `.cmd` files should be ASCII, CRLF, and no BOM.

In committed documentation and examples, use `<A4PUMP_ROOT>` for the installed application folder. A generic example root is `C:\A4PumpKit`.

Recommended structure:

```text
<A4PUMP_ROOT>\
  a4ctl\
    a4ctl.exe
  config\
    pumps.json
    profiles.json
    syringes.json
    recipes.json
  nis_cmd\
    pump_test_dryrun.cmd
    pump_write_fast30.cmd
    pump_start_fast30.cmd
    pump_stop_all.cmd
  nis_logs\
```

NIS macro example:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_fast30.cmd");
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

Committed examples should use `<A4PUMP_ROOT>` or a generic root such as `C:\A4PumpKit`. Local `.cmd` files may contain absolute paths, but those files should not be committed if they include user-specific paths. If local `.cmd` wrappers are needed, copy the template and edit locally.

During experiments, COM port changes should be made in `config\pumps.json`, not by hard-coding COM values in wrapper files. For example, set the port to `COMx`, where `COMx` is the USB-TTL adapter port shown by Windows Device Manager or `a4ctl list-ports`.

Logging is intentionally split:

- `nis_logs\nis_exec.log` is written by `.cmd` wrappers.
- `logs\a4pump_YYYYMMDD.csv` is written by `a4ctl.exe` and `A4PumpGUI.exe`.

Log unification is future work.
