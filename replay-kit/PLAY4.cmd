@echo off
REM  PLAY the newest v4 tape. Run from ANY screen - the savestate carries the mode and pulls the
REM  sim to character select itself. The UI may render briefly garbled while the shell catches up.
REM  Drag a specific .rr4 onto this file to play that one.
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
echo   PLAYING %TAPE%
echo.
python rrtape4.py play "%TAPE%"
echo.
pause
