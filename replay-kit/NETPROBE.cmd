@echo off
REM  READ-ONLY observer for a REAL ONLINE MATCH. Writes nothing to the game, ever.
REM  Runs until you press ENTER in this window. Pass a number for a hard time cap.
setlocal
cd /d "%~dp0"
echo.
echo   netprobe - READ ONLY. Go queue ranked, play as long as you like.
echo   Press ENTER in THIS window when you are done to print the summary.
echo.
python netprobe.py %*
echo.
pause
