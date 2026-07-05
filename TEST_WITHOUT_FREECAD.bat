@echo off
chcp 65001 >nul
title FreeCAD Agent - Quick test (without FreeCAD)
cd /d "%~dp0"

rem --- Find a Python interpreter (first "py", then "python") ---
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE ( where python >nul 2>nul && set "PYEXE=python" )
if not defined PYEXE (
  echo  ERROR: Python not found. Install Python and try again.
  echo  https://www.python.org/downloads/  (tick "Add python.exe to PATH")
  pause & exit /b 1
)

echo  This test does NOT use FreeCAD: it only checks that the engine works.
echo.
echo  1) Starting the engine in a new window...
start "FreeCAD Agent - Engine" cmd /k "cd /d %~dp0engine && %PYEXE% bridge_server.py"

echo  2) Waiting 3 seconds for the engine to start...
timeout /t 3 >nul

echo  3) Starting a FAKE add-on that connects to the engine:
echo.
%PYEXE% "%~dp0tests\mock_addon_client.py"

echo.
echo  If above you see "handshake", a command "executed" and one "rejected":
echo  the engine works. (The engine window stays open; close it manually or
echo  press Ctrl+C in it.)
pause
