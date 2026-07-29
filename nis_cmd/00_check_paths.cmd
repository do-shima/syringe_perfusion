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
if not exist "%CFG%\profiles.json" (echo ERROR: missing profiles.json >> "%LOG%" & exit /b 3)
if not exist "%CFG%\syringes.json" (echo ERROR: missing syringes.json >> "%LOG%" & exit /b 3)
if not exist "%CFG%\recipes.json" (echo ERROR: missing recipes.json >> "%LOG%" & exit /b 3)
"%A4%" --config-dir "%CFG%" config-path >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] EXIT=%RC% >> "%LOG%"
exit /b %RC%
