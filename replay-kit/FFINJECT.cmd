@echo off
REM  Measure input-injection fidelity under fast-forward.
REM  Be IN A FIGHT with the game window FOCUSED.
setlocal
cd /d "%~dp0"
echo.
echo   ffinject.py
echo.
python ffinject.py %*
echo.
pause
