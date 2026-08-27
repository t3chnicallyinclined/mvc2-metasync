@echo off
REM  T1(a): do the per-character DAT slabs mutate during a fight?
REM  Read-only. Be IN A FIGHT with the game window FOCUSED (it pauses when unfocused).
setlocal
cd /d "%~dp0"
echo.
echo   slabwatch.py
echo.
python slabwatch.py %*
echo.
pause
