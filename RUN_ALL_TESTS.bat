@echo off
title FreeCAD Agent - Automated tests (without FreeCAD)
cd /d "%~dp0"

rem --- Find a Python interpreter (first "py", then "python") ---
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE ( where python >nul 2>nul && set "PYEXE=python" )
if not defined PYEXE (
  echo  ERROR: Python not found. Install Python and try again.
  echo  https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause & exit /b 1
)

set "LOG=%~dp0tests_output.txt"
echo FreeCAD Agent - test run > "%LOG%"
echo Interpreter: %PYEXE% >> "%LOG%"
echo. >> "%LOG%"

echo  ============================================================
echo   FreeCAD Agent - test suite (does NOT use FreeCAD or Ollama)
echo   A full log is also written to: tests_output.txt
echo  ============================================================
echo.

set "FAIL=0"

call :runtest "1/21 Bridge basics"            tests\test_bridge_core.py
call :runtest "2/21 Command validation"       tests\test_validation.py
call :runtest "3/21 Structured round-trip"    tests\test_roundtrip.py
call :runtest "4/21 Planning brain"           tests\test_brain.py
call :runtest "5/21 Ollama client"            tests\test_ollama_client.py
call :runtest "6/21 Expanded vocabulary"      tests\test_vocabulary_exec.py
call :runtest "7/21 Document perception"      tests\test_perception.py
call :runtest "8/21 Full natural-language"    tests\test_user_prompt_roundtrip.py
call :runtest "9/21 Edge selection"           tests\test_edge_selection.py
call :runtest "10/21 Ollama auto-start"       tests\test_ollama_launch.py
call :runtest "11/21 Cancellation"            tests\test_cancel.py
call :runtest "12/21 AI timeout config"       tests\test_timeout_config.py
call :runtest "13/21 Create sketch"           tests\test_create_sketch.py
call :runtest "14/21 Sketch-extrude link"     tests\test_extrude_link.py
call :runtest "15/21 Move and rotate"         tests\test_transform.py
call :runtest "16/21 Id-chaining helpers"     tests\test_idchain.py
call :runtest "17/21 Id-chaining guard"       tests\test_idchain_guard.py
call :runtest "18/21 Mirror and array"        tests\test_duplicate.py
call :runtest "19/21 Sketch on face + pocket" tests\test_sketch_on_face.py
call :runtest "20/21 Topology flip"           tests\test_flip.py
call :runtest "21/21 Engine launcher"         tests\test_launcher.py

echo  ============================================================
if "%FAIL%"=="0" (
  echo   RESULT: ALL TESTS PASSED.
  echo RESULT: ALL TESTS PASSED. >> "%LOG%"
) else (
  echo   RESULT: AT LEAST ONE TEST FAILED ^(see above^).
  echo RESULT: AT LEAST ONE TEST FAILED >> "%LOG%"
)
echo  ============================================================
echo.
echo  Press any key to close this window...
pause >nul
exit /b 0

:runtest
echo  [%~1] ...
echo ===== %~1 ===== >> "%LOG%"
%PYEXE% "%~dp0%~2" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo       FAILED  ^(details in tests_output.txt^)
  set "FAIL=1"
) else (
  echo       passed
)
echo. >> "%LOG%"
exit /b 0
