@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "A4=%ROOT%\a4ctl\a4ctl.exe"
set "CFG=%ROOT%\config"
set "LOGDIR=%ROOT%\nis_logs"
set "LOG=%LOGDIR%\nis_exec.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo [%DATE% %TIME%] CONFIG=%CFG% >> "%LOG%"
if not exist "%A4%" (echo ERROR: missing %A4% >> "%LOG%" & exit /b 2)
if not exist "%CFG%\pumps.json" (echo ERROR: missing pumps.json >> "%LOG%" & exit /b 3)
"%A4%" --config-dir "%CFG%" run-profile --pump IN --profile fast30_1ml --dish-id NIS --condition start_fast30_IN --trigger-source NIS >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] EXIT=%RC% >> "%LOG%"
exit /b %RC%
