@echo off
chcp 65001 >nul
title FreeCAD Agent - Engine (DEBUG standalone mode)
cd /d "%~dp0engine"

rem --- Find a Python interpreter (first "py", then "python") ---
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE ( where python >nul 2>nul && set "PYEXE=python" )

if not defined PYEXE (
  echo.
  echo  ============================================================
  echo   ERROR: Python is not installed or not on the PATH.
  echo   Download it from:  https://www.python.org/downloads/
  echo   During installation TICK "Add python.exe to PATH".
  echo  ============================================================
  echo.
  pause
  exit /b 1
)

echo  ============================================================
echo   FreeCAD Agent - engine in DEBUG standalone mode  (interpreter: %PYEXE%)
echo  ------------------------------------------------------------
echo   YOU NORMALLY DO NOT NEED THIS FILE ANYMORE.
echo   In FreeCAD just open the panel and click "Connect": the
echo   engine now starts BY ITSELF. This window is only for
echo   debugging - it runs the engine as a standalone server and
echo   writes the discovery file. To use it, tick the panel option
echo   "Debug: attach to a manually-started engine" before Connect.
echo  ------------------------------------------------------------
echo   The engine will AUTO-START the local AI (Ollama) if it is
echo   installed but not yet running - just wait a few seconds.
echo   LEAVE THIS WINDOW OPEN. To stop the engine: press Ctrl + C.
echo  ============================================================
echo.

%PYEXE% bridge_server.py

echo.
echo  --- The engine has stopped. You can close this window. ---
pause
