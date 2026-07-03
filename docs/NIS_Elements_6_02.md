# NIS-Elements 6.02 integration

## Purpose

This document describes the validated NIS-Elements 6.02 workflow for triggering A4 syringe pump control from ND Acquisition.

The recommended project workflow is:

1. NIS-Elements runs a `.cmd` file with `Int_ExecProgram`.
2. The `.cmd` wrapper calls `a4ctl.exe`.
3. `a4ctl.exe` reads configuration from an explicit `--config-dir`.
4. Pump-side logs are written separately from NIS wrapper logs.

## Confirmed environment

- NIS-Elements 6.02
- `Int_ExecProgram` confirmed
- PowerShell execution confirmed
- `.cmd` execution from NIS confirmed
- `.cmd` execution from PowerShell confirmed
- Pump control from both PowerShell and NIS macro confirmed
- Current Nikon PC COM3 confirmed
- Root directory: `D:\data\Do\Syringe_pump`

COM番号は環境依存です。Current Nikon PCではCOM3で動作確認済みですが、一般運用では `config/pumps.json` の `IN.port` を実COMに合わせてください。

## Directory layout

```text
D:\data\Do\Syringe_pump\
  a4ctl\
    a4ctl.exe
  config\
    pumps.json
    profiles.json
    syringes.json
    recipes.json
  nis_cmd\
    00_check_paths.cmd
    pump_list_ports.cmd
    pump_test_dryrun.cmd
    pump_write_fast30.cmd
    pump_start_fast30.cmd
    pump_start_fast30_async.cmd
    pump_start_fast30_worker.cmd
    pump_stop_all.cmd
    pump_jog_forward_500ms.cmd
    pump_jog_forward_500ms_dryrun.cmd
    pump_start_after_30s_recipe.cmd
  recipes\
    nis_start_after_30s.json
  nis_logs\
```

## Required files

- `D:\data\Do\Syringe_pump\a4ctl\a4ctl.exe`
- `D:\data\Do\Syringe_pump\config\pumps.json`
- `D:\data\Do\Syringe_pump\config\profiles.json`
- `D:\data\Do\Syringe_pump\config\syringes.json`
- `D:\data\Do\Syringe_pump\config\recipes.json`
- `.cmd` wrappers in `D:\data\Do\Syringe_pump\nis_cmd\`
- Optional recipe file: `D:\data\Do\Syringe_pump\recipes\nis_start_after_30s.json`
- Log directory: `D:\data\Do\Syringe_pump\nis_logs\`

Run `00_check_paths.cmd` first after copying files or changing the root directory.

## Macro syntax

NIS-Elements 6.02 runs an external file with:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_start_fast30.cmd");
```

Use the exact path matching the installed folder.

If path problems occur, first test with:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_test_dryrun.cmd");
```

Then check:

```text
D:\data\Do\Syringe_pump\nis_logs\nis_exec.log
```

Important behavior:

- `Int_ExecProgram` executes an external file only.
- NIS does not directly report external process launch success.
- NIS does not directly report external process completion.
- In ND Acquisition, NIS time counting continues while the external file is running.
- External file launch has a small lag.

## Recommended ND Acquisition setup

Use this method when imaging should continue while stimulation starts. This is the standard recommended workflow for this project.

1. Open ND Acquisition.
2. Create two time phases.
3. Configure the timelapse settings for each phase.
4. Open Advanced.
5. Set `Advanced for` to Time Phase 2.
6. Insert the macro in `Execute before Time phase`.
7. Use `pump_start_fast30.cmd` as the external command.
8. Run the acquisition.

Example macro:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_start_fast30.cmd");
```

Behavior:

- `pump_start_fast30.cmd` is executed immediately before Time Phase 2.
- Imaging continues during Time Phase 2.
- External launch has a small lag.
- Use a dye test to measure the actual liquid arrival frame.
- Prefer a direct start command over a recipe wait when NIS can schedule the phase boundary.

## Alternative No Acquisition phase setup

Use this method when imaging should stop during external command execution, or when a non-imaging phase should be explicit.

1. Open ND Acquisition.
2. Create three time phases.
3. Set Phase 2 to `No Acquisition`.
4. Open Advanced.
5. Set `Advanced for` to Time Phase 2.
6. Insert the macro in `Execute before Time phase`.
7. Set Phase 2 duration long enough to cover the external command execution.
8. Run the acquisition.

Behavior:

- The external file is launched before Phase 2.
- Imaging is not performed during Phase 2.
- Phase 2 duration should include the expected external command runtime.
- External file launch has a small lag.

This method is useful for non-imaging write or setup commands.

## Macro examples

Dry-run:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_test_dryrun.cmd");
```

Write Fast-30:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_write_fast30.cmd");
```

Start saved Fast-30:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_start_fast30.cmd");
```

Async start:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_start_fast30_async.cmd");
```

Stop all:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_stop_all.cmd");
```

Start after 30 s using recipe:

```text
Int_ExecProgram("D:\data\Do\Syringe_pump\nis_cmd\pump_start_after_30s_recipe.cmd");
```

## Preflight checklist

- USB-TTL adapter connected to the same USB port
- COM port confirmed
- `config/pumps.json` `IN.port` updated
- `pump_list_ports.cmd` run
- `pump_test_dryrun.cmd` run
- `pump_write_fast30.cmd` run
- A4 LCD speed/time checked
- Tubing primed
- Needle and waste path checked
- Jog test performed if safe
- `pump_stop_all.cmd` tested

## Experiment workflow

Before acquisition:

1. Run `pump_write_fast30.cmd`.
2. Confirm A4 display speed/time.
3. Prime the line and check needle/waste path.

During acquisition:

1. NIS executes `pump_start_fast30.cmd` before the selected phase.
2. A4 starts the saved Fast-30 profile.

After acquisition:

1. Run `pump_stop_all.cmd` if needed.
2. Save the ND2 file and copy logs.

## Troubleshooting

PowerShell works but NIS does not:

- Check the `Int_ExecProgram` path.
- Check the folder spelling: `Syringe_pump`.
- Check `nis_logs\nis_exec.log`.
- Test with `pump_test_dryrun.cmd`.

COM list is not obtained:

- Run `pump_list_ports.cmd` in PowerShell.
- Check the config path.
- Check the `a4ctl.exe` path.

Pump does not move:

- Confirm the COM port.
- Confirm `pump_write_fast30.cmd` was run.
- Confirm the A4 LCD speed/time.
- Confirm dry-run is not being used.

NIS appears to ignore execution:

- Remember that `Int_ExecProgram` cannot directly report status.
- Check `nis_logs\nis_exec.log`.

Timing is shifted:

- A small launch lag is expected.
- Use a dye arrival test.
- Prefer a direct start command over recipe wait if NIS can schedule the phase boundary.

## Known limitations

- NIS does not directly return process status.
- NIS cannot confirm external file completion.
- There is external launch lag.
- Current logs are separate.
- Log unification is future work.

## Logging status

Current logging is intentionally split:

1. `nis_logs\nis_exec.log`
   - Created by `.cmd` wrappers.
   - Records NIS-side execution start/end and exit code.
2. `logs\a4pump_YYYYMMDD.csv`
   - Created by `a4ctl` and `A4PumpGUI`.
   - Records pump commands, profiles, dry-run, command hex, responses, recipe IDs, and block IDs.

Do not treat these as one combined log. Log unification is future work.
