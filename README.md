# A4 Syringe Pump Control

Version: V3.2  
GUI: Tkinter/ttk + clam theme + custom Style  
Control: USB-TTL UART  
Distribution: PyInstaller one-folder  
Dependencies: Python + pyserial for source run; no Python needed for built app

## Overview

A4/QHZS系シリンジポンプをUSB-TTL UART経由で制御するための軽量Pythonアプリです。V3.2では、1台運用を標準にしたGUI、manual hold、bounded jog、速度・時間設定のA4本体書き込み、プロファイル実行、Recipe Builder、CSVログ、アプリアイコン/ロゴアセット管理、PyInstaller配布をサポートします。

研究室内の顕微鏡PCや実験用Windows PCで、追加GUI依存を増やさずに動かすことを前提にしています。

## Key Features

- OUTポンプを任意に有効化できるSingle-pump mode
- 自動停止を伴うManual hold forward/reverse
- 指定時間だけ動かして必ず停止するBounded jog
- A4本体への速度・時間設定書き込み
- Terumo SS-05LZ 5 mL Luer-lock用Fast-30 profile
- Step cardsとvalidationを備えたRecipe Builder
- 実機なしでコマンド確認できるDry-run mode
- live / dry-run両方を残すCSV logging
- PyInstaller one-folder Windows app build
- 画像が無くても落ちないicon / logo asset loading

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

## Installation from Source

PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m pytest
python run_gui.py
```

CLIもsource runできます。

```powershell
python -m syringe_perfusion.cli --help
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

- `A4PumpGUI.exe` はGUI版です。
- `a4ctl.exe` はCLI版です。
- `pathlib` backport packageが入っているとPyInstallerが失敗することがあります。その場合は `pip uninstall pathlib` または `conda remove pathlib` で削除してください。
- `build/`, `dist/`, `*.spec` はbuild outputなのでGit管理対象にしません。

## Quick Start: GUI

Launch:

```powershell
python run_gui.py
```

Built app:

```powershell
dist\A4PumpGUI\A4PumpGUI.exe
```

Pages:

- Dashboard: app status、connection summary、quick actions、safety statusを確認します。
- Pumps: IN/OUT pump settings、OUT enable/disable、connection test、manual hold、jog、STOP ALLを扱います。
- Run: 保存済みA4設定をIN onlyで開始します。OUT enabled時はOUT only、Push-pull、Two forwardも使えます。
- Profiles: profileを選び、計算済みspeed/timeをpreviewし、A4へwriteします。必要な場合だけstart after writeを使います。
- Calculator: speed/timeを計算し、計算結果をA4へwriteします。
- Recipes: Block Library、Recipe Steps、Inspectorの3ペインRecipe Builderです。

Manual holdは、ボタン押下中に `q6h4d` または `q6h5d` を送り、ボタン解放、カーソル離脱、auto-stop timeout、stop操作で `q6h6d` を送ります。Jogは指定msだけmanual forward/reverseを実行し、その後stopを送ります。

GUIでは `Esc` でSTOP ALLを送ります。

## Quick Start: CLI

Serial port一覧:

```powershell
python -m syringe_perfusion.cli list-ports
```

Manual forwardとstop:

```powershell
python -m syringe_perfusion.cli send --pump IN --action manual-forward
python -m syringe_perfusion.cli send --pump IN --action stop
```

500 msのJog forward:

```powershell
python -m syringe_perfusion.cli jog --pump IN --direction forward --duration-ms 500
```

Fast-30 settingsを書き込む:

```powershell
python -m syringe_perfusion.cli write-profile --pump IN --profile fast30_1ml --save
```

保存済みprofileを開始:

```powershell
python -m syringe_perfusion.cli run-profile --pump IN --profile fast30_1ml
```

有効な全pumpを停止:

```powershell
python -m syringe_perfusion.cli stop-all
```

`--dry-run` を付けると、serial portを開かずにoutgoing commandsを確認できます。

## Fast-30 Profile

Fast-30は、確認済みシリンジで1 mL / 30 secを狙うreference profileです。

- Syringe: Terumo SS-05LZ 5 mL Luer-lock
- Speed: 15.37 mm/min
- Duration: 30 sec
- Measured mass: 1.001, 1.007, 0.994, 1.000, 1.007 g
- Average: about 1.002 g

このprofileのsettings write commands:

```text
q1h15d
q2h37d
q3h00d
q4h00d
q5h30d
q6h1d
```

Profile writingはデフォルトではpumpを開始しません。GUIでは `Start after write`、CLIでは `--start-after-write` を使えますが、明示的に開始したい場合だけ使ってください。

## Single-Pump and OUT Pump Mode

GUIはINだけを有効にしたsingle-pump operationをサポートします。

- OUT disabledは1台運用の標準的なmodeです。
- OUT disabledではOUT COM portは空欄で構いません。
- OUT enabledではOUT COM portが必須です。
- OUT only、Push-pull、Two forwardはOUT enabled時だけ使えます。
- Recipe Builderはdry-run / run前にdisabled pumpの使用を検出します。

Pump enable stateは `config/pumps.json` に保存され、Pumps pageからも変更できます。

## Recipe Builder

V3.2 Recipe Builderは3ペイン構成です。

- Block Library: recipe blockを追加します。
- Recipe Steps: card-style step listで手順を確認します。
- Inspector: selected blockを編集し、validation messagesを確認します。

対応操作:

- Add block
- Select and edit block
- Move Up / Down
- Duplicate
- Delete
- Validate
- Dry-run
- Run

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

Command logsは次に保存されます。

```text
logs/a4pump_YYYYMMDD.csv
```

Dry-run commandsもログに残ります。重要な列:

```text
timestamp, pump, port, command, outgoing_hex, response, mode,
profile, speed_mm_min, duration_s, recipe_id, block_id
```

ログは実験時のcommand historyとdry-run verificationを残すためのものです。

## Application Icon and Assets

V3.2ではapplication iconとlogoのstatic asset loadingを追加しています。

```text
assets/
  icons/
  logo/
```

画像が無い場合もappは安全に無視して起動します。PNG icon/logoが存在すればGUIが読み込みます。PyInstaller buildでは `assets` directoryを同梱し、`assets/icons/app.ico` が存在する場合だけexecutable iconとして使います。

Recommended app icon direction:

- No text, letters, numbers, labels, or tiny UI details.
- Use a simplified syringe pump silhouette.
- Use a high-contrast design that remains recognizable at 32 x 32 px.
- Recommended master size: 1024 x 1024.
- Export PNG sizes under `assets/icons/` and a Windows ICO as `assets/icons/app.ico`.
- Put larger logo images under `assets/logo/`.

## Safety Notes

- 初回確認はシリンジなし、または空シリンジで行ってください。
- Manual hold / jogでは、Stop、auto-stop、Esc停止が動作することを確認してください。
- 実液体ラインでは、針位置、廃液先、閉塞、ライン接続を確認してから実行してください。
- `Start after write` is OFF by default. Keep it OFF unless immediate start is intentional.
- GUIではSTOP ALLボタンとEscキーで停止できます。
- A4 `V` pin must not be connected.

## Project Structure

```text
syringe_perfusion/
  syringe_perfusion/
  config/
  recipes/
  assets/
  scripts/
  tests/
```

Main entry points:

- `run_gui.py`: GUI application
- `run_cli.py`: PyInstaller用CLI entry point
- `python -m syringe_perfusion.cli`: source run用CLI

## Development Status

- Version: V3.2
- Tests: pytest 57 passed
- GUI exe build confirmed
- A4 actual command sending confirmed
- Tested command behavior: lowercase ASCII with CRLF over 9600 baud USB-TTL UART

## Version History

- V1: serial command wrapper, config, CLI/GUI, logging.
- V2: Recipe Builder.
- V2.1: single-pump mode and settings writer.
- V3.0: left navigation and card UI.
- V3.1: UI polish and step cards.
- V3.2: icon/assets and PyInstaller app metadata.
