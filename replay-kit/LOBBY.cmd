@echo off
REM  READ-ONLY probe: who are the two FIGHTERS, and who is merely in the lobby?
REM  Audited: no WriteProcessMemory, no VirtualProtect, read-only handle. It cannot disturb the game.
REM
REM  RUN THIS DURING A LIVE 3-SEAT ARCADE MATCH - the cabinet spectating, two people fighting.
REM  That is the case the tray gets wrong today, and the one nobody has observed yet.
REM
REM  THE GATE: the cabinet's SteamID must appear ONLY under "NON-FIGHTER PARTICIPANTS",
REM  and the D1/D2/D5 falsifier lines must be clean. If so, the fix is safe to write.
REM
REM    LOBBY.cmd          watch, re-snapshotting on every change (press a key to stop)
REM    LOBBY.cmd --once   one snapshot
REM    LOBBY.cmd --hex    add raw record dumps
setlocal
cd /d "%~dp0"
python lobbyprobe.py %*
echo.
pause
