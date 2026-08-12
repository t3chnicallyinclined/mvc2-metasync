@echo off
REM ── Reload "MvC Collection Live Skins" ──────────────────────────────
REM Double-click to (re)launch the app. Kills any running instance first,
REM then starts a fresh hidden dev host so the window comes up clean.
title MvC Live Skins launcher
echo Reloading MvC Collection Live Skins...
powershell -NoProfile -Command ^
  "Get-Process mvc-live-skins -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue;" ^
  "Get-CimInstance Win32_Process -Filter \"Name='cargo.exe'\" -EA SilentlyContinue | Where-Object { $_.CommandLine -like '*tauri*dev*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue };" ^
  "Start-Sleep -Milliseconds 600;" ^
  "Start-Process 'C:\Users\trist\.cargo\bin\cargo.exe' -ArgumentList 'tauri','dev' -WorkingDirectory 'C:\Users\trist\projects\mvc-live-skins\src-tauri' -WindowStyle Hidden -RedirectStandardOutput \"$env:TEMP\mvc-ls-dev.out.log\" -RedirectStandardError \"$env:TEMP\mvc-ls-dev.err.log\""
echo.
echo Launched. The window will appear in a few seconds (first run may build).
timeout /t 3 >nul
