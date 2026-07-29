@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "A4=%ROOT%\a4ctl\a4ctl.exe"
set "CFG=%ROOT%\config"
set "LOGDIR=%ROOT%\nis_logs"
set "LOG=%LOGDIR%\nis_exec.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo [%DATE% %TIME%] CONFIG=%CFG% >> "%LOG%"
echo [%DATE% %TIME%] START pump_jog_forward_500ms_dryrun >> "%LOG%"
if not exist "%A4%" (echo ERROR: missing %A4% >> "%LOG%" & exit /b 2)
if not exist "%CFG%\pumps.json" (echo ERROR: missing pumps.json >> "%LOG%" & exit /b 3)
"%A4%" --config-dir "%CFG%" jog --pump IN --direction forward --duration-ms 500 --dish-id NIS --condition jog_forward_dryrun --trigger-source NIS --dry-run >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] END pump_jog_forward_500ms_dryrun EXIT=%RC% >> "%LOG%"
exit /b %RC%
