# NIS-Elements 6.02 integration

## Shared Active Config

NIS-Elements runs a tracked `.cmd` wrapper with `Int_ExecProgram`. The wrapper calls `a4ctl.exe` and always passes the same external config used by the standard GUI installation:

```bat
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "A4=%ROOT%\a4ctl\a4ctl.exe"
set "CFG=%ROOT%\config"
set "LOGDIR=%ROOT%\nis_logs"
set "LOG=%LOGDIR%\nis_exec.log"
```

`CFG` contains `pumps.json`, `profiles.json`, `syringes.json`, and `recipes.json`. These four files are managed as one directory. Do not create `nis_cmd\config`, do not edit `_internal\default_config`, and do not hard-code COM ports in wrappers.

GUI Setup displays the Active Config and provides `Copy NIS CFG line`. If the GUI is switched away from `<A4PUMP_ROOT>\config`, update the NIS wrapper CFG deployment to the same path. Confirm both sides with:

```powershell
<A4PUMP_ROOT>\a4ctl\a4ctl.exe --config-dir "<A4PUMP_ROOT>\config" config-path
```

## Distribution

```text
<A4PUMP_ROOT>\
  A4PumpGUI.exe
  a4ctl\
    a4ctl.exe
  config\
    pumps.json
    profiles.json
    syringes.json
    recipes.json
  nis_cmd\
    00_check_paths.cmd
    pump_test_dryrun.cmd
    pump_write_in_out.cmd
    pump_start_pushpull_fast30.cmd
    pump_stop_all.cmd
  nis_logs\
  _internal\
```

The actual COM names differ on each PC. Configure them in GUI Setup and save to `<A4PUMP_ROOT>\config\pumps.json`. The public defaults and wrappers do not contain the local IN/OUT COM numbers.

## Macro examples

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_write_in_out.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_pushpull_fast30.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_stop_all.cmd");
```

Generic Windows example:

```text
Int_ExecProgram("C:\A4PumpKit\nis_cmd\pump_stop_all.cmd");
```

Run `00_check_paths.cmd` and `pump_test_dryrun.cmd` before live use. Check `<A4PUMP_ROOT>\nis_logs\nis_exec.log`; every wrapper records `CONFIG=<CFG>`, command output/error, and exit code.

## Wrapper rules

- Resolve ROOT from `%~dp0`; never depend on the NIS current directory.
- Always use `--config-dir "%CFG%"`.
- One `a4ctl` command per physical line.
- Never use the batch continuation character `^`.
- Store tracked files as ASCII and CRLF.
- Do not include personal paths or COM numbers.
- Return the `a4ctl` exit code.
- In `pump_write_in_out.cmd`, an IN failure prevents the OUT write.

## Experiment workflow

1. Open GUI Setup, select and save the IN/OUT ports.
2. Confirm GUI Active Config is `<A4PUMP_ROOT>\config`.
3. Run `00_check_paths.cmd`.
4. Run `pump_test_dryrun.cmd`.
5. Run `pump_write_in_out.cmd` and verify both A4 displays.
6. Let NIS call `pump_start_pushpull_fast30.cmd` at the chosen phase boundary.
7. Use `pump_stop_all.cmd` when required.

NIS only launches the external wrapper; it does not directly confirm completion. External launch has a small lag, so validate liquid-arrival timing with a dye test.

## Safety

- Verify IN and OUT are different USB serial ports.
- Confirm tubing, priming, syringe direction, and waste path.
- Start with dry-run and a non-biological setup.
- Keep GUI STOP ALL / Esc and `pump_stop_all.cmd` available.
- Actual UART/live behavior requires an explicit hardware test and is not exercised by pytest.
