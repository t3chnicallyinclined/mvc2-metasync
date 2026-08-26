@echo off
REM  PLAY the newest tape. Run this when YOU are ready.
REM  Be on the CHARACTER SELECT screen (cursor anywhere - the tape restores it).
REM  Drag a specific .rr3 onto this file to play that one instead.
setlocal
cd /d "%~dp0"
set TAPE=%~1
if "%TAPE%"=="" for /f "delims=" %%F in ('dir /b /o-d *.rr3 2^>NUL') do if not defined TAPE set TAPE=%%F
if "%TAPE%"=="" (
  echo.
  echo   No .rr3 tape found. Run REC.cmd first.
  echo.
  pause
  exit /b 1
)
echo.
echo   PLAYING %TAPE%
echo.
python rrtape3.py play "%TAPE%"
echo.
pause
