# A4 Syringe Pump Control

Version: V3.2  
GUI: Tkinter/ttk + clam theme + custom Style  
Control: USB-TTL UART  
Distribution: PyInstaller one-folder  
Dependencies: Python + pyserial for source run; no Python needed for built app

## Overview

A4/QHZS系シリンジポンプをUSB-TTL UART経由で制御する軽量Python/Windowsアプリです。V3.2では、GUI、CLI、Single Pump Mode、Manual Hold、Jog、速度・時間設定の書き込み、Recipe Builder、NIS-Elements連携、PyInstaller配布、アプリアイコン/アセット管理に対応しています。

研究室内の顕微鏡PCや実験用Windows PCで、追加GUI依存を増やさずに動かすことを前提にしています。

## Key Features

- USB-TTL UART control for A4 syringe pump
- Single pump mode with optional OUT pump
- Manual hold and bounded jog
- Write speed/time settings to A4
- Fast-30 profile
- Recipe Builder
- Dry-run
- CSV logging
- NIS-Elements 6.02 integration via `Int_ExecProgram`
- PyInstaller Windows app
- Icon and logo assets

## Current Validated Setup

- Windows
- NIS-Elements 6.02
- `a4ctl.exe` called from `.cmd` files
- `A4PumpGUI.exe` confirmed working
- `.cmd` wrappers confirmed from PowerShell and NIS macro
- A4 pump control confirmed from PowerShell and NIS macro
- PowerShell and NIS macro execution confirmed
- The actual COM port and installation directory depend on the microscope PC.
- Set `config/pumps.json` and local `.cmd` wrappers accordingly.

In this document, `<A4PUMP_ROOT>` denotes the installation folder of the built application. For example, `C:\A4PumpKit`.

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

The actual COM port depends on the Windows PC. Check it with `list-ports` and set `config/pumps.json` accordingly. For example, set `IN.port` to `COMx`, where `COMx` is the USB-TTL adapter port shown by Windows Device Manager or `a4ctl list-ports`.

## Hardware Connection

A4 controller connector:

```text
T R G V
```

Connection:

```text
A4 T -> USB-TTL RXD
A4 R -> USB-TTL TXD
A4 G -> USB-TTL GND
A4 V -> not connected
```

Important:

- A4 `V` must not be connected to 3.3 V or 5 V.
- A4本体は通常の12 V電源で動かします。
- USB-TTL変換器はCP2102N、CH340Gなどを使います。
- USB-RS232変換器やUSB D+/D-直結ケーブルは使いません。

## Communication Protocol

実機では小文字ASCIIコマンドで動作確認済みです。大文字コマンドではなく、小文字で送信してください。

- Baudrate: 9600
- Data format: 8N1
- Flow control: none
- Terminator: CRLF (`\r\n`)
- Encoding: ASCII lowercase commands

| Command | Meaning |
| --- | --- |
| `q6h2d` | auto forward |
| `q6h3d` | auto reverse |
| `q6h4d` | manual forward |
| `q6h5d` | manual reverse |
| `q6h6d` | stop |
| `q1hxxd` | speed integer |
| `q2hxxd` | speed decimal |
| `q3hHHd` | hour |
| `q4hMMd` | minute |
| `q5hSSd` | second |
| `q6h1d` | save |

Example settings for speed 15.37 mm/min and duration 30 sec:

```text
q1h15d
q2h37d
q3h00d
q4h00d
q5h30d
q6h1d
```

## Windows App Build

PyInstaller one-folder build:

```powershell
scripts\build_windows.bat
```

Generated applications:

```text
dist\A4PumpGUI\A4PumpGUI.exe
dist\a4ctl\a4ctl.exe
```

Notes:

- `A4PumpGUI.exe` is the GUI app.
- `a4ctl.exe` is the CLI app used by NIS `.cmd` wrappers.
- `assets` are included in the build.
- `assets/icons/app.ico` is used as the executable icon if present.
- `pathlib` backport package can break PyInstaller. If needed, remove it with `pip uninstall pathlib` or `conda remove pathlib`.

## Quick Start: Source

PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m pytest
python run_gui.py
```

CLI source run:

```powershell
python -m syringe_perfusion.cli --help
python -m syringe_perfusion.cli list-ports
```

## Quick Start: Built App

GUI:

```powershell
dist\A4PumpGUI\A4PumpGUI.exe
```

CLI:

```powershell
dist\a4ctl\a4ctl.exe list-ports
```

## Quick Start: CLI

Serial port一覧:

```powershell
python -m syringe_perfusion.cli list-ports
```

Fast-30 settingsを書き込む:

```powershell
python -m syringe_perfusion.cli write-profile --pump IN --profile fast30_1ml --save
```

保存済みFast-30 profileを開始:

```powershell
python -m syringe_perfusion.cli run-profile --pump IN --profile fast30_1ml
```

500 msのJog forward:

```powershell
python -m syringe_perfusion.cli jog --pump IN --direction forward --duration-ms 500
```

有効な全pumpを停止:

```powershell
python -m syringe_perfusion.cli stop-all
```

`--dry-run` を付けると、serial portを開かずにoutgoing commandsを確認できます。

## NIS-Elements Integration Summary

Detailed setup is documented in [docs/NIS_Elements_6_02.md](docs/NIS_Elements_6_02.md). The `.cmd` wrapper policy is documented in [nis_cmd/README.md](nis_cmd/README.md). Macro-only examples are in [docs/NIS_macro_examples.txt](docs/NIS_macro_examples.txt).

NIS-Elements 6.02では、次の形式で外部ファイルを実行します。

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_fast30.cmd");
```

Replace `<A4PUMP_ROOT>` with the actual installation folder on the microscope PC.

This project uses NIS to call `.cmd` files. Each `.cmd` file then calls `a4ctl.exe` with an explicit `--config-dir`, so execution does not depend on the NIS current directory.

NIS `Int_ExecProgram` only launches an external file. NIS does not directly report whether the process started successfully or whether it has completed. Check `nis_logs/nis_exec.log` and `logs/a4pump_YYYYMMDD.csv` after execution. Log unification is future work.

Path and COM-port policy for committed documentation:

- Do not hard-code personal paths in committed documentation.
- Use `<A4PUMP_ROOT>` in README and docs.
- Local deployment paths should be kept only in local `.cmd` files or local notes that are not committed.
- The actual COM port should be configured in `config/pumps.json`.

Representative NIS macro examples:

```text
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_test_dryrun.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_write_fast30.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_start_fast30.cmd");
Int_ExecProgram("<A4PUMP_ROOT>\nis_cmd\pump_stop_all.cmd");
```

Recommended acquisition mode:

- Use ND Acquisition Advanced.
- Select `Advanced for` Time Phase 2.
- Insert the macro in `Execute before Time phase`.
- Use two time phases when imaging should continue during stimulation.
- `pump_start_fast30.cmd` runs immediately before Time Phase 2, and Time Phase 2 imaging continues.

Alternative acquisition mode:

- Use three time phases.
- Set Phase 2 to `No Acquisition`.
- Insert the macro in `Execute before Time phase` for Phase 2.
- Use this when imaging should stop during external command execution, or when an explicit non-imaging phase is needed.

NIS external program launch has a small lag. Measure actual liquid arrival timing with dye and align analysis to the observed arrival frame.

## Fast-30 Profile

Fast-30 is a reference profile targeting 1 mL / 30 sec with the confirmed syringe.

- Syringe: Terumo SS-05LZ 5 mL Luer-lock
- Speed: 15.37 mm/min
- Duration: 30 sec
- Target volume: 1000 uL
- Measured mass: 1.001, 1.007, 0.994, 1.000, 1.007 g
- Average: about 1.002 g

Settings write commands:

```text
q1h15d
q2h37d
q3h00d
q4h00d
q5h30d
q6h1d
```

Write Fast-30 before acquisition with:

```text
<A4PUMP_ROOT>\nis_cmd\pump_write_fast30.cmd
```

Profile writing does not start the pump by default. GUI `Start after write` and CLI `--start-after-write` should be used only when immediate start is intentional.

## Single Pump Mode

GUI supports IN-only single pump operation.

- OUT disabled is the default for one-pump operation.
- OUT COM may be blank when OUT is disabled.
- OUT COM is required when OUT is enabled.
- Push-pull, OUT only, and Two forward require OUT enabled.
- STOP ALL skips disabled pumps.
- Recipe Builder validates disabled pump usage before dry-run and run.

Pump enable state is stored in `config/pumps.json` and can also be changed from the GUI.

## Recipe Builder

V3.2 Recipe Builder has three main areas:

- Block Library
- Recipe Steps
- Inspector

Recipe Steps uses step cards for editing and review. Recipes can be validated, dry-run, and run. Disabled pump validation runs before execution.

Available block types:

- `pump_start`
- `pump_stop`
- `manual_jog`
- `stop_all`
- `wait`
- `log_marker`
- `prompt_check`

OUT disabled時にOUTを使うrecipeは、実行前のvalidationでエラーになります。

## Logging

Current logging is intentionally split:

1. `nis_logs/nis_exec.log`
   - Created by `.cmd` wrappers.
   - Records NIS-side execution start/end and exit code.
2. `logs/a4pump_YYYYMMDD.csv`
   - Created by `a4ctl` and `A4PumpGUI`.
   - Records pump commands, profiles, dry-run, command hex, responses, recipe IDs, and block IDs.

Do not treat these as one combined log. Log unification is future work and is planned for a future version.

## Application Icon and Assets

V3.2 includes application icon and logo asset loading.

```text
assets/
  icons/
  logo/
```

PNG icon/logo files are loaded by the GUI when present. PyInstaller includes the `assets` directory and uses `assets/icons/app.ico` as the executable icon when present.

Recommended app icon direction:

- No text, letters, numbers, labels, or tiny UI details.
- Use a simplified syringe pump silhouette.
- Use a high-contrast design that remains recognizable at 32 x 32 px.
- Recommended master size: 1024 x 1024.
- Export PNG sizes under `assets/icons/` and a Windows ICO as `assets/icons/app.ico`.
- Put larger logo images under `assets/logo/`.

## Safety

- First test without syringe or with an empty syringe.
- Confirm the COM port before each experiment day.
- Write Fast-30 before acquisition.
- Confirm A4 LCD speed/time.
- Check tubing, priming, needle position, and waste path.
- Use STOP ALL and Esc.
- Measure actual liquid arrival delay using dye.
- NIS external program launch has a small lag.
- A4 `V` pin must not be connected to USB-TTL power.

## Project Structure

```text
syringe_perfusion/
  syringe_perfusion/
  config/
  recipes/
  assets/
  docs/
  nis_cmd/
  scripts/
  tests/
```

Main entry points:

- `run_gui.py`: GUI application
- `run_cli.py`: PyInstaller CLI entry point
- `python -m syringe_perfusion.cli`: source-run CLI

## Development Status

- Version: V3.2
- Tests: pytest 57 passed
- GUI exe build confirmed
- NIS macro execution confirmed
- PowerShell and NIS macro both confirmed to control pump
- Tested command behavior: lowercase ASCII with CRLF over 9600 baud USB-TTL UART
- Log unification pending

## Version History

- V1: serial command wrapper, config, CLI/GUI, logging.
- V2: Recipe Builder.
- V2.1: single-pump mode and settings writer.
- V3.0: left navigation and card UI.
- V3.1: UI polish.
- V3.2: icon/assets and NIS-ready Windows app.
- V3.3 or future: log unification.
