@echo off
title FreeCAD Agent - Install add-on (local copy)
setlocal enabledelayedexpansion

rem ============================================================================
rem  Installs this add-on into FreeCAD's Mod folder as a REAL LOCAL COPY (not a
rem  junction). Reading the add-on from a cloud-synced folder (kDrive) caused
rem  FreeCAD to occasionally load half-synced files; a local copy is stable.
rem
rem  Re-run this file after the add-on is updated to refresh the local copy.
rem  It prints the VERSION it just installed, so you can tell at a glance that
rem  the update went through. Administrator is NOT required.
rem ============================================================================

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "BASE=%APPDATA%\FreeCAD"

echo.
echo  Add-on source : "%REPO%"
echo  FreeCAD base  : "%BASE%"
echo.

set "INSTALLED=0"

rem 1) Versioned profiles: ...\FreeCAD\v1-1\Mod, v1-0\Mod, etc.
for /d %%D in ("%BASE%\v*") do (
  call :install "%%~fD\Mod"
)

rem 2) Fallback: classic non-versioned path (older FreeCAD).
if "!INSTALLED!"=="0" (
  call :install "%BASE%\Mod"
)

echo.
if "!INSTALLED!"=="0" (
  echo  ============================================================
  echo   NO installation succeeded. Open FreeCAD, go to the Python
  echo   console and tell me what this prints:
  echo     import FreeCAD; print^(FreeCAD.getUserAppDataDir^(^)^)
  echo  ============================================================
) else (
  echo  ============================================================
  echo   DONE ^(successful installs: !INSTALLED!^). Now:
  echo    1) Close and reopen FreeCAD.
  echo    2) From the workbench bar pick "FreeCAD Agent".
  echo    3) The panel appears on the right.
  echo   To use it: click "Connect" in the panel. The engine starts
  echo   by itself ^(no START_ENGINE.bat needed^).
  echo   After Connect, the panel log must report the SAME version
  echo   printed above.
  echo  ============================================================
)
echo.
echo  Press any key to close this window...
pause >nul
exit /b 0

rem ---------------------------------------------------------------------------
:install
set "MODDIR=%~1"
set "DEST=%MODDIR%\FreeCADAgent"
echo  -^> installing into: "%DEST%"
if not exist "%MODDIR%" mkdir "%MODDIR%" 2>nul

rem Remove any previous install: a junction (rmdir) or a real folder (rmdir /S).
if exist "%DEST%" (
  echo     removing previous install...
  rmdir "%DEST%" 2>nul
  if exist "%DEST%" rmdir /S /Q "%DEST%" 2>nul
)

rem Copy a clean local snapshot (skip caches and git).
robocopy "%REPO%" "%DEST%" /E /XD "__pycache__" ".git" /XF "*.pyc" /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP >nul
if %ERRORLEVEL% GEQ 8 (
  echo     COPY FAILED here ^(robocopy error %ERRORLEVEL%^).
) else (
  if exist "%DEST%\InitGui.py" (
    echo     OK. Version just installed:
    findstr /C:"ADDON_VERSION =" "%DEST%\addon\ai_copilot\bridge_client.py"
    findstr /C:"ENGINE_VERSION =" "%DEST%\engine\bridge_server.py"
    set /a INSTALLED+=1
  ) else (
    echo     not installed here ^(InitGui.py missing after copy^).
  )
)
exit /b 0
