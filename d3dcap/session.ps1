# RETRO RECEIPTS - Path B: ONE session, both measurements.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File session.ps1
#
# Launches the game ONCE and, on your cue, runs both open questions back to back:
#
#   1. THE RNG PROBE  (game at FULL SPEED - nothing is being captured yet)
#      Does the DC LCG live inside the GGPO rollback region? If it does, "anchor + inputs"
#      really is the whole replay feed. `replay-kit/verify.py rng` is a falsification
#      harness -- it exists to DISPROVE the claim, not to confirm it.
#
#   2. THE BURST      (the game WILL crawl for this part, and only this part)
#      N seconds of consecutive frames, packed into a playable .seq.
#
# Why one script: these need opposite things from the game. The probe needs 600 sim frames at
# full speed; the burst copies every texture and both buffers every frame. Run separately that
# is two launches and two trips to the character select. So the shim is launched with
# D3DCAP_MANUAL=1 -- it captures NOTHING until this script says so -- and the crawl is confined
# to the burst at the end.
#
#   -Seconds N   seconds of match to record in the burst (default 5)
#   -Frames N    sim frames for the RNG probe (default 600 = 10s at 60fps)
#   -SkipRng     burst only
#   -SkipBurst   probe only
#   -Keep        do not wipe previous captures first

[CmdletBinding()]
param(
    [double]$Seconds = 5,
    [int]$Frames = 600,
    [switch]$SkipRng,
    [switch]$SkipBurst,
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$here   = $PSScriptRoot
$root   = Split-Path $here -Parent
$capDir = Join-Path $env:TEMP 'rrcap'
$log    = Join-Path $capDir 'd3dcap.log'
$kit    = Join-Path $root 'replay-kit'
$PROC   = 'MarvelVsCapcomFightingCollection'
$burst  = [int][math]::Round($Seconds * 60)

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Game { Get-Process $PROC -ErrorAction SilentlyContinue | Select-Object -First 1 }
function Rule { Say ("=" * 78) Cyan }

if (-not $Keep -and (Test-Path $capDir)) {
    Say "[prep] clearing previous captures"
    Remove-Item "$capDir\*" -Force -Recurse -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force $capDir | Out-Null

# The shim must not arm on a timer: the RNG probe needs the game at full speed.
$env:D3DCAP_MANUAL = '1'
$env:D3DCAP_BURST  = "$burst"

Say "[build] compiling d3dcap..."
$g = Game
if ($g) { Stop-Process -Id $g.Id -Force; while (Game) { Start-Sleep -Milliseconds 300 }; Start-Sleep -Seconds 2 }
$out = & cmd /c "`"$(Join-Path $here 'build.bat')`"" 2>&1
if ($LASTEXITCODE -ne 0 -or ($out | Select-String -Quiet 'BUILD FAILED')) {
    $out | Select-String -Pattern 'error|BUILD' | ForEach-Object { Say "  $_" Red }
    exit 1
}
Say "[build] OK" Green

Say "[game] launching SUSPENDED (hooked before any game code runs)..."
$r = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'launch_suspended.ps1') 2>&1
if (-not ($r -match 'LAUNCHED')) { Say "[game] launch failed: $r" Red; exit 1 }
Say "[game] $($r | Select-String 'LAUNCHED')" Green
Say "[inject] injected pre-execution; capture is HELD until this script arms it" Green

$deadline = (Get-Date).AddMinutes(2)
while (-not (Game) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
if (-not (Game)) { Say "[game] process did not survive launch" Red; exit 1 }

Say ""
Rule
Say " GET INTO A MATCH." Cyan
if (-not $SkipRng) {
    Say ""
    Say " Pick RNG-HEAVY characters if you can - Storm, Blackheart, Sentinel." Cyan
    Say " The first measurement looks for the random-number generator, and a generator" Cyan
    Say " nobody draws from is invisible. Supers and projectiles on screen is what it needs." Cyan
}
Say ""
Say " The game is running at FULL SPEED. Nothing is being captured yet." Green
Rule
Say ""
Read-Host " Press ENTER once you are IN A FIGHT and swinging"

# ── 1. the RNG probe, at full speed ──────────────────────────────────────────────────────────────
if (-not $SkipRng) {
    Say ""
    Rule
    Say " 1/2  RNG PROBE - keep fighting for the next ~$([math]::Round($Frames/60.0))s" Cyan
    Rule
    Push-Location $kit
    & python verify.py rng $Frames
    $rngExit = $LASTEXITCODE
    Pop-Location
    if ($rngExit -ne 0) { Say "[rng] probe failed (exit $rngExit) - continuing to the burst" Yellow }
    Say ""
    Say "[rng] done. Read the RESULT line above: an LCG INSIDE blk means anchor+inputs is" Green
    Say "      the whole feed. Nothing in blk is not proof of absence - re-run with --exe." Green
}

# ── 2. the burst ─────────────────────────────────────────────────────────────────────────────────
if ($SkipBurst) { Say ""; Say "[done] skipping the burst as asked" Green; exit 0 }

Say ""
Rule
Say " 2/2  BURST - $burst consecutive frames = $Seconds s of GAME time" Cyan
Say "" Cyan
Say " THE GAME WILL CRAWL from the moment you press ENTER until the burst is full." Yellow
Say " That is the capture copying every texture and both buffers, every frame." Yellow
Say " Keep playing through it - GAME frames are what is being counted, not seconds." Yellow
Rule
Say ""
Read-Host " Press ENTER to start recording"

# The ARM file is the shim's manual trigger. It retries internally until a frame lands in a
# match, so an arm during a menu costs one discarded frame rather than the run.
New-Item -ItemType File -Force (Join-Path $capDir 'ARM') | Out-Null
Say "[burst] armed - recording..."

$logLen = 0
$stop = (Get-Date).AddMinutes(20)
$best = 0
while ((Get-Date) -lt $stop) {
    Start-Sleep -Seconds 2
    if (-not (Game)) { Say "[game] exited" Yellow; break }

    if (Test-Path $log) {
        $len = (Get-Item $log).Length
        if ($len -gt $logLen) {
            $fs = [IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
            $null = $fs.Seek($logLen, 'Begin')
            $sr = New-Object IO.StreamReader($fs)
            $sr.ReadToEnd() -split "`r?`n" |
                Where-Object { $_ -match '\[burst\]|\[write\]|\[buf\]|\[tex\]|\[emit\]' } |
                ForEach-Object { Say "  $_" DarkGray }
            $sr.Close(); $fs.Close(); $logLen = $len
        }
    }

    # Consecutive frame numbers on disk are the real progress: the log only reports every 60.
    $ids = @(Get-ChildItem "$capDir\frame_*.ndjson" -ErrorAction SilentlyContinue |
             Where-Object { $_.Length -gt 0 } |
             ForEach-Object { [int]($_.BaseName -replace 'frame_', '') } | Sort-Object)
    $run = 0; $prev = -99; $best = 0
    foreach ($i in $ids) {
        if ($i -eq $prev + 1) { $run++ } else { $run = 1 }
        $prev = $i
        if ($run -gt $best) { $best = $run }
    }
    if ($best -ge $burst - 2) { Say "[burst] $best consecutive frames on disk" Green; break }
}

if ($best -lt 2) { Say "[burst] nothing consecutive was recorded" Red; exit 2 }

Say ""
Rule
Say " PACKING" Cyan
Rule
& python (Join-Path $here 'replay\pack_sequence.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Say ""
Say "[next] serve it and watch:" Green
Say "  python $(Join-Path $here 'replay\serve.py')" Green
Say "  then open http://localhost:8099/player.html" Green
