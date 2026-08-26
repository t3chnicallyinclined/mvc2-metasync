@echo off
REM  RECORD a v4 replay tape: character-select savestate + inputs + ground-truth checkpoints.
REM  Be on the CHARACTER SELECT screen. Starts instantly and records the WHOLE match.
REM  It stops by itself when a team is wiped; press ENTER any time to stop and SAVE.
REM  Pass a number of seconds to force a fixed length instead.
setlocal
cd /d "%~dp0"
set SECS=%~1
if "%SECS%"=="" set SECS=0
for /f "tokens=1-4 delims=:.," %%a in ("%TIME: =0%") do set STAMP=%%a%%b%%c
echo.
if "%SECS%"=="0" (echo   RECORDING until the match ends  -^>  m%STAMP%.rr4) else (echo   RECORDING %SECS%s  -^>  m%STAMP%.rr4)
echo   GO - pick your characters and play the match out.
echo   Stops on its own at a team wipe.  Press ENTER any time to stop and SAVE.
echo.
python rrtape4.py rec m%STAMP% %SECS%
echo.
echo   Done. Move your cursor somewhere else, then run PLAY4.cmd
echo.
pause
