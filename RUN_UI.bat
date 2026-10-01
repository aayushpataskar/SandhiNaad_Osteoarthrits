@echo off
REM Double-click to start the SandhiNaad desktop app.
cd /d "%~dp0host"
py -3.12 app.py 2>nul || py -3.11 app.py 2>nul || python app.py
if errorlevel 1 pause
