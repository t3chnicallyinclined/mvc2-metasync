@echo off
REM  Read-only probe: dumps blk/arena/mode/seat map/rollbacks, the live fighter digest, and settles
REM  the blk+0x32500 conflict (reader.rs "phase" vs the six fighter self-pointers). Writes nothing.
setlocal
cd /d "%~dp0"
python rrtape4.py probe
echo.
pause
