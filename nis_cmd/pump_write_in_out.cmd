@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "A4=%ROOT%\a4ctl\a4ctl.exe"
set "CFG=%ROOT%\config"
set "LOGDIR=%ROOT%\nis_logs"
set "LOG=%LOGDIR%\nis_exec.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo [%DATE% %TIME%] CONFIG=%CFG% >> "%LOG%"
echo [%DATE% %TIME%] START pump_write_in_out >> "%LOG%"
if not exist "%A4%" (echo ERROR: missing %A4% >> "%LOG%" & exit /b 2)
if not exist "%CFG%\pumps.json" (echo ERROR: missing pumps.json >> "%LOG%" & exit /b 3)
"%A4%" --config-dir "%CFG%" write-profile --pump IN --profile fast30_1ml --save --dish-id NIS --condition write_fast30_IN --trigger-source NIS >> "%LOG%" 2>&1
if errorlevel 1 goto :end
"%A4%" --config-dir "%CFG%" write-profile --pump OUT --profile drain30_1ml --save --dish-id NIS --condition write_fast30_OUT --trigger-source NIS >> "%LOG%" 2>&1
:end
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] END pump_write_in_out EXIT=%RC% >> "%LOG%"
exit /b %RC%
