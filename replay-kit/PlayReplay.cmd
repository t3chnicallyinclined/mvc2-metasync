@echo off
REM ---------------------------------------------------------------------------
REM  RETRO RECEIPTS - match replay
REM
REM  Double-click, or drag a .rrtape onto this file.
REM  MARVEL vs CAPCOM Fighting Collection must already be RUNNING and in a match
REM  (any match - the tape overwrites the simulation state with its own).
REM
REM  The tape carries the complete deterministic state (the region MvC2 registers
REM  with GGPO for rollback) plus the input stream. Restoring one and feeding the
REM  other reproduces the match exactly.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

REM No tape given? Use the NEWEST .rrtape beside this script, so a fresh recording is picked up
REM automatically and a stale one can't be replayed by accident.
set TAPE=%~1
if "%TAPE%"=="" for /f "delims=" %%F in ('dir /b /o-d *.rrtape 2^>NUL') do if not defined TAPE set TAPE=%%F

if not exist "%TAPE%" (
  echo.
  echo   Tape not found: %TAPE%
  echo   Drag a .rrtape file onto this script, or put take1.rrtape beside it.
  echo.
  pause
  exit /b 1
)

tasklist /FI "IMAGENAME eq MarvelVsCapcomFightingCollection.exe" 2>NUL | find /I "MarvelVsCapcom" >NUL
if errorlevel 1 (
  echo.
  echo   MvC2 is not running. Start the game and get into a match, then run this again.
  echo.
  pause
  exit /b 1
)

echo.
echo   RETRO RECEIPTS - replaying %TAPE%
echo.
python rrtape.py play "%TAPE%"
echo.
pause
