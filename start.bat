@echo off
rem Designed Living: double-click to start. Close this window to stop it.
cd /d "%~dp0"
py app.py %*
if errorlevel 1 pause
