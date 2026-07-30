@echo off
setlocal
cd /d "%~dp0\.."
if defined A4_RELEASE_BUILD (
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\generate_build_info.ps1" -BuildType "release-candidate" -RequireClean
) else (
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\generate_build_info.ps1" -BuildType "development"
)
if errorlevel 1 exit /b %ERRORLEVEL%
set "STAGE=%CD%\build\pyinstaller-dist"
set "WORK=%CD%\build\pyinstaller-work"
set "KIT=%CD%\dist\A4PumpGUI"
pyinstaller --noconfirm --distpath "%STAGE%" --workpath "%WORK%" A4PumpGUI.spec
if errorlevel 1 exit /b %ERRORLEVEL%
pyinstaller --noconfirm --distpath "%STAGE%" --workpath "%WORK%" a4ctl.spec
if errorlevel 1 exit /b %ERRORLEVEL%
if not exist "%KIT%" mkdir "%KIT%"
xcopy "%STAGE%\A4PumpGUI\*" "%KIT%\" /E /I /Y >nul
if errorlevel 1 exit /b %ERRORLEVEL%
if not exist "%KIT%\a4ctl" mkdir "%KIT%\a4ctl"
xcopy "%STAGE%\a4ctl\*" "%KIT%\a4ctl\" /E /I /Y >nul
if errorlevel 1 exit /b %ERRORLEVEL%
if exist "%KIT%\_internal\config" rmdir /S /Q "%KIT%\_internal\config"
if exist "%KIT%\a4ctl\_internal\config" rmdir /S /Q "%KIT%\a4ctl\_internal\config"
if not exist "%KIT%\config" mkdir "%KIT%\config"
if not exist "%KIT%\config\pumps.json" copy "config\pumps.json" "%KIT%\config\pumps.json" >nul
if not exist "%KIT%\config\profiles.json" copy "config\profiles.json" "%KIT%\config\profiles.json" >nul
if not exist "%KIT%\config\syringes.json" copy "config\syringes.json" "%KIT%\config\syringes.json" >nul
if not exist "%KIT%\config\recipes.json" copy "config\recipes.json" "%KIT%\config\recipes.json" >nul
if not exist "%KIT%\nis_cmd" mkdir "%KIT%\nis_cmd"
xcopy "nis_cmd\*" "%KIT%\nis_cmd\" /E /I /Y >nul
if errorlevel 1 exit /b %ERRORLEVEL%
if not exist "%KIT%\nis_logs" mkdir "%KIT%\nis_logs"
echo Build completed: %KIT%
