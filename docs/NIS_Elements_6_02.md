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
- The actual COM port and installation directory depend on the microscope PC.
- Set `config/pumps.json` and local `.cmd` wrappers accordingly.

In this document, `<A4PUMP_ROOT>` denotes the installation folder of the built application. For example, `C:\A4PumpKit`.

The actual COM port depends on the Windows PC. Check it with `list-ports` and set `config/pumps.json` accordingly. For example, set `IN.port` to `COMx`, where `COMx` is the USB-TTL adapter port shown by Windows Device Manager or `a4ctl list-ports`.

## Directory layout

```text
<A4PUMP_ROOT>\
  a4ctl\
    a4ctl.exe
  config\
  nis_cmd\
  recipes\
  nis_logs\
```

## Required files

- `<A4PUMP_ROOT>\a4ctl\a4ctl.exe`
- `<A4PUMP_ROOT>\config\pumps.json`
- `<A4PUMP_ROOT>\config\profiles.json`
- `<A4PUMP_ROOT>\config\syringes.json`
- `<A4PUMP_ROOT>\config\recipes.json`
- `.cmd` wrappers in `<A4PUMP_ROOT>\nis_cmd\`
- Optional recipe file: `<A4PUMP_ROOT>\recipes\nis_start_after_30s.json`
- Log directory: `<A4PUMP_ROOT>\nis_logs\`

Run `00_check_paths.cmd` first after copying files or changing the root directory.

## Macro syntax

NIS-Elements 6.02 runs an external file with:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_fast30.cmd");
```

Replace `<A4PUMP_ROOT>` with the actual installation folder on the microscope PC. A generic Windows example is:

```text
Int_ExecProgram("C:\A4PumpKit\nis_cmd\pump_start_fast30.cmd");
```

If path problems occur, first test with:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_test_dryrun.cmd");
```

Then check:

```text
<A4PUMP_ROOT>\nis_logs\nis_exec.log
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
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_fast30.cmd");
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
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_test_dryrun.cmd");
```

Write Fast-30:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_write_fast30.cmd");
```

Start saved Fast-30:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_fast30.cmd");
```

Async start:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_fast30_async.cmd");
```

Stop all:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_stop_all.cmd");
```

Start after 30 s using recipe:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_after_30s_recipe.cmd");
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
