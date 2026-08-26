@echo off
REM  READ-ONLY falsification harness. Writes nothing to the game.
REM  Run it DURING a busy fight (supers/projectiles on screen) - several checks need live action.
REM    VERIFY.cmd          - everything
REM    VERIFY.cmd rng      - the decisive one: is the sim RNG inside blk or outside it?
REM    VERIFY.cmd pool     - find the projectile/assist/effect object pool from the draw list
REM    VERIFY.cmd cam      - settle the eyeY-vs-camera-zoom label
REM    VERIFY.cmd reg      - what GGPO actually registered, and which arm of the fork we are on
setlocal
cd /d "%~dp0"
python verify.py %*
echo.
pause
