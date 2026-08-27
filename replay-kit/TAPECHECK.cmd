@echo off
REM  Watches for the agent's spooled tape and grades it the moment it appears.
REM  START THIS FIRST, then play a match - the uploader deletes tapes after upload,
REM  so this copies them into replay-kit\tapes-kept\ before they vanish.
REM  Read-only w.r.t. the game; it only reads files the agent writes.
setlocal
cd /d "%~dp0"
python checktape.py watch
echo.
pause
