@echo off
REM  RECORD a replay tape. Run this when YOU are ready.
REM  Anchors the instant it starts, then records 20 seconds (or pass a number of seconds).
REM  Be on the CHARACTER SELECT screen when you run it, then pick characters and fight.
setlocal
cd /d "%~dp0"
set SECS=%~1
if "%SECS%"=="" set SECS=20
REM %TIME% pads single-digit hours with a SPACE -> "take 53443.rr3". Strip it.
for /f "tokens=1-4 delims=:.," %%a in ("%TIME: =0%") do set STAMP=%%a%%b%%c
set NAME=take%STAMP%
echo.
echo   RECORDING %SECS%s  -^>  %NAME%.rr3
echo   GO - pick your characters and fight.
echo.
python rrtape3.py rec %NAME% %SECS%
echo.
echo   Done. Now move your cursor somewhere else and run PLAY.cmd
echo.
pause
