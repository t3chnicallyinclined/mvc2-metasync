@echo off
REM  READ-ONLY. Verifies GGPO's confirmed input ring and compares it against the latch we poll.
REM  Writes nothing to the game, ever. Safe during a real ranked match.
REM  ONLINE ONLY - GGPO does not register a session offline, so training mode reports "no session".
setlocal
cd /d "%~dp0"
echo.
echo   inputring - READ ONLY.
echo.
echo   1. Queue a RANKED (or custom) match - it must be ONLINE. No wager needed.
echo   2. Once the fight has STARTED, leave this window running.
echo   3. Press any key in THIS window when the set is done to print the summary.
echo.
python inputring.py %*
echo.
pause
