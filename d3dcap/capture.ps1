# RETRO RECEIPTS - Path B: one-command capture session.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File capture.ps1
#
# Does the whole loop: rebuild if the source changed (closing the game first, since the DLL is
# file-locked while loaded), launch the game via Steam if it is not running, inject, then WATCH for
# captures and print a summary automatically. Capturing is AUTOMATIC (every 8s) -- you just play.
#
# Flags:
#   -Force      kill a running game for a rebuild without asking
#   -NoLaunch   never start the game; just wait for you to start it
#   -NoWatch    inject and exit (no auto-summary)

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoLaunch,
    [switch]$NoWatch
)

$ErrorActionPreference = 'Stop'
$here    = $PSScriptRoot
$dll     = Join-Path $here 'd3dcap.dll'
$src     = Join-Path $here 'dllmain.cpp'
$build   = Join-Path $here 'build.bat'
$summ    = Join-Path $here 'summarize.py'
$capDir  = Join-Path $env:TEMP 'rrcap'
$logFile = Join-Path $capDir 'd3dcap.log'
$APPID   = 2634890                                # MvC Fighting Collection (reader.rs:891)
$PROC    = 'MarvelVsCapcomFightingCollection'     # mem.rs:217 matches on this prefix

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Game { Get-Process $PROC -ErrorAction SilentlyContinue | Select-Object -First 1 }

# ── 1. rebuild if the source is newer than the DLL ───────────────────────────────────────────────
$needBuild = (-not (Test-Path $dll)) -or ((Get-Item $src).LastWriteTime -gt (Get-Item $dll).LastWriteTime)
if ($needBuild) {
    Say "[build] dllmain.cpp is newer than d3dcap.dll - rebuild needed." Yellow
    $g = Game
    if ($g) {
        # The DLL is mapped into the game, so it is locked; and LoadLibrary on an already-loaded path
        # does NOT re-run DllMain, so a code change needs a full game restart anyway.
        if (-not $Force) {
            Say "        The game is running and has the old DLL mapped (locked + stale hooks)." Yellow
            $a = Read-Host "        Close the game now and rebuild? [Y/n]"
            if ($a -and $a -notmatch '^[Yy]') { Say "[build] aborted." Red; exit 1 }
        }
        Say "[build] closing the game (pid $($g.Id))..."
        Stop-Process -Id $g.Id -Force
        while (Game) { Start-Sleep -Milliseconds 300 }
        Start-Sleep -Seconds 2
    }
    Say "[build] compiling..."
    $out = & cmd /c "`"$build`"" 2>&1
    if ($LASTEXITCODE -ne 0 -or ($out | Select-String -Quiet 'BUILD FAILED')) {
        $out | Select-String -Pattern 'error|BUILD' | ForEach-Object { Say "        $_" Red }
        Say "[build] FAILED." Red
        exit 1
    }
    Say "[build] OK - $((Get-Item $dll).Length) bytes" Green
} else {
    Say "[build] d3dcap.dll is current." Green
}

# ── 2. make sure the game is running ─────────────────────────────────────────────────────────────
$g = Game
if (-not $g) {
    if ($NoLaunch) {
        Say "[game] not running (-NoLaunch). Waiting for you to start it..." Yellow
    } else {
        Say "[game] launching via Steam (appid $APPID)..."
        Start-Process "steam://rungameid/$APPID"
    }
    # Poll fast: CreateInputLayout / CreateVertexShader / CreatePixelShader can only be captured if
    # we are already resident when they are called, and ID3D11VertexShader has NO GetBytecode -- there
    # is no retroactive path. The old 5s sleep guaranteed we missed everything created during startup.
    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Game) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 100 }
    $g = Game
    if (-not $g) { Say "[game] never appeared - start it and re-run." Red; exit 1 }
    Say "[game] appeared pid=$($g.Id) - injecting immediately (retrying until it takes)" Yellow
}
Say "[game] running pid=$($g.Id)" Green

# ── 3. inject (skip if already mapped) ───────────────────────────────────────────────────────────
$already = $false
try { $already = [bool]($g.Modules | Where-Object { $_.ModuleName -eq 'd3dcap.dll' }) } catch { }
if ($already) {
    Say "[inject] d3dcap.dll already mapped - skipping." Green
} else {
    # A very early process may not be ready for CreateRemoteThread yet, so retry rather than sleeping
    # a fixed amount -- every retry we skip is more shaders created without us watching.
    $ok = $false
    for ($try = 1; $try -le 40; $try++) {
        $r = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'inject.ps1') 2>&1
        if ($r -match 'INJECTED') { Say "[inject] OK (attempt $try)" Green; $ok = $true; break }
        if ($r -match 'GAME_NOT_RUNNING') { Say "[inject] game vanished" Red; exit 1 }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ok) { Say "[inject] FAILED after 40 attempts" Red; exit 1 }
    Start-Sleep -Milliseconds 500
}

if ($NoWatch) { Say "`nInject done. Capturing automatically every 8s; files land in $capDir"; exit 0 }

# ── 4. watch for captures and auto-summarize ─────────────────────────────────────────────────────
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Say "[watch] python not on PATH - captures will still be written to $capDir" Yellow }

$seen = @{}
if (Test-Path $capDir) { Get-ChildItem "$capDir\shot_*.bmp","$capDir\frame_*.ndjson" -ErrorAction SilentlyContinue | ForEach-Object { $seen[$_.Name] = $true } }

Say ""
Say "==============================================================================" Cyan
Say " READY - just play. A SCREENSHOT of the real backbuffer is taken every 8s." Cyan
Say " TRAINING MODE is ideal: offline, and you can throw a super on demand." Cyan
Say " ** Shaders/layouts are only capturable if we were resident when the ARCADE" Cyan
Say "    TITLE loaded. Watch the [diag] 'captured at creation' counts climb as you" Cyan
Say "    enter MvC2 -- if they stay low, we injected too late; restart the game." Cyan
Say " (Avoid the attract-mode demo - it renders the wrong characters.)" Cyan
Say " Each capture writes a .bmp AND a per-draw .ndjson for the SAME frame." Cyan
Say " Draw counters are inline (MinHook); a full breakdown prints for rich frames." Cyan
Say " Ctrl+C to stop." Cyan
Say "==============================================================================" Cyan
Say ""

$logLen = if (Test-Path $logFile) { (Get-Item $logFile).Length } else { 0 }
$script:bestLen  = 0
$script:bestFile = $null

while ($true) {
    Start-Sleep -Milliseconds 700

    # surface new DLL log lines (arming, hook status, errors)
    if (Test-Path $logFile) {
        $len = (Get-Item $logFile).Length
        if ($len -gt $logLen) {
            $fs = [IO.File]::Open($logFile, 'Open', 'Read', 'ReadWrite')
            $null = $fs.Seek($logLen, 'Begin')
            $sr = New-Object IO.StreamReader($fs)
            $sr.ReadToEnd() -split "`r?`n" | Where-Object { $_ } | ForEach-Object { Say "  $_" DarkGray }
            $sr.Close(); $fs.Close()
            $logLen = $len
        }
    }

    # screenshots
    $new = Get-ChildItem "$capDir\shot_*.bmp" -ErrorAction SilentlyContinue |
           Where-Object { -not $seen.ContainsKey($_.Name) }
    foreach ($f in $new) {
        Start-Sleep -Milliseconds 300
        $seen[$f.Name] = $true
        $f.Refresh()
        if ($f.Length -eq 0) { Say "[shot] $($f.Name) is EMPTY" Red; continue }
        Say "[shot] $($f.Name)  $([math]::Round($f.Length/1MB,2)) MB" Green
    }

    # per-draw inventories (same frame number as the screenshot beside it)
    $inv = Get-ChildItem "$capDir\frame_*.ndjson" -ErrorAction SilentlyContinue |
           Where-Object { -not $seen.ContainsKey($_.Name) }
    foreach ($f in $inv) {
        Start-Sleep -Milliseconds 400
        $seen[$f.Name] = $true
        $f.Refresh()
        if ($f.Length -eq 0) { Say "[inv]  $($f.Name) EMPTY - no draws in that frame" Red; continue }
        if (-not $py) { Say "[inv]  $($f.Name) $([math]::Round($f.Length/1KB,0)) KB" Green; continue }
        & python $summ $f.FullName --brief
        # print the full breakdown for the richest frame seen so far
        if ($f.Length -gt ($script:bestLen * 1.15)) {
            $script:bestLen = $f.Length
            Say ""
            Say "  ---- richest frame so far: $($f.Name) ----" Green
            & python $summ $f.FullName
            Say ""
        }
    }
}
