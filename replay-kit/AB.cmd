@echo off
REM  THE A/B FALSIFICATION TEST. Uses the newest .rr4 tape (drag a specific one onto this file
REM  to use that instead). Takes about 3x the tape length.
REM
REM    A) restore the tape's character-select anchor -> replay the tape
REM    B) restore the anchor -> play RANDOM inputs for 900 frames (churns any hidden state)
REM    C) restore the anchor -> replay the SAME tape
REM
REM  A == C means nothing outside blk survives an anchor restore to affect a match, whatever
REM  generator the game uses and wherever it lives. A != C falsifies the whole replay model.
REM  ⚠ This WRITES to the game (the anchor + inputs), same as PLAY4. It will play random garbage
REM     during step B - that is the point. Nothing is permanent; restart the game if it gets stuck.
setlocal
cd /d "%~dp0"
set TAPE=%~1
if "%TAPE%"=="" for /f "delims=" %%F in ('dir /b /o-d *.rr4 2^>NUL') do if not defined TAPE set TAPE=%%F
if "%TAPE%"=="" (
  echo.
  echo   No .rr4 tape found. Run REC4.cmd first.
  echo.
  pause
  exit /b 1
)
echo.
echo   A/B TEST on %TAPE%
echo.
python rrtape4.py ab "%TAPE%"
echo.
pause
