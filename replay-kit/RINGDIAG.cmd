@echo off
REM  READ-ONLY one-shot diagnostic. Writes nothing to the game, ever.
REM  Start this FIRST, then queue a match - it waits for the GGPO session to come up.
setlocal
cd /d "%~dp0"
echo.
echo   ringdiag - READ ONLY, one shot.
echo.
echo   1. Leave this window open.
echo   2. Queue an ONLINE match (ranked or custom - no wager needed).
echo   3. It waits for the session, samples for ~11s once the fight starts, then prints.
echo.
python ringdiag.py %*
echo.
pause
