@echo off
REM Double-click this file to install everything SandhiNaad needs.
REM It runs setup.ps1 (Python, UI packages, arduino-cli, ESP32 core 2.0.17,
REM Adafruit libraries) and compiles the firmware as a test.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -SkipArduinoIDE
echo.
echo ============================================================
echo  Done. A copy of everything above is in setup_log.txt
echo ============================================================
pause
