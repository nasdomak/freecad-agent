@echo off
title FreeCAD Agent - Check the local AI (Ollama)
cd /d "%~dp0"

echo  ============================================================
echo   FreeCAD Agent - local AI (Ollama) check
echo  ============================================================
echo.

where ollama >nul 2>nul
if errorlevel 1 (
  echo  [X] Ollama is NOT installed ^(the 'ollama' command was not found^).
  echo.
  echo      Install it from:  https://ollama.com/download
  echo      Then run:         ollama pull qwen3:4b
  echo.
  echo  Natural language will be disabled until Ollama is installed, but
  echo  structured commands in the panel keep working without it.
  echo.
  echo  Press any key to close this window...
  pause >nul
  exit /b 1
)

echo  [OK] Ollama is installed. Installed models:
echo.
ollama list
echo.

echo  Checking that the test model "qwen3:4b" is present...
ollama list | findstr /i "qwen3" >nul 2>nul
if errorlevel 1 (
  echo  [!] The model "qwen3:4b" is NOT installed.
  echo      Get it with:   ollama pull qwen3:4b
) else (
  echo  [OK] A qwen3 model is available. Natural language is ready.
)
echo.
echo  Press any key to close this window...
pause >nul
exit /b 0
