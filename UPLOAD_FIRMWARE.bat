@echo off
REM Plug in the ESP32, close Arduino Serial Monitor, then double-click this.
cd /d "%~dp0"
echo Connected boards / ports:
arduino-cli board list
echo.
set /p PORT=Type the ESP32 COM port (e.g. COM5) and press Enter:
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -SkipArduinoIDE -Upload -Port %PORT%
pause
