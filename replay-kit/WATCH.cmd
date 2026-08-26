@echo off
REM  READ-ONLY. Follows the game's mode byte through every menu, so you can SEE which screens a
REM  replay tape can be anchored at instead of taking anyone's word for it.
REM  Walk the game through TRAINING, VERSUS, ARCADE and a LOBBY with this running.
REM  Press any key to stop. Writes nothing to the game.
setlocal
cd /d "%~dp0"
python verify.py watch
echo.
pause
