# RETRO RECEIPTS - Path B: GUIDED capture session. One launch, several short bursts, each one a
# move you are told to perform, each packed into its own playable .seq.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File session-guided.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File session-guided.ps1 -Seconds 3 -Steps "sent-rocket=Sentinel: rocket punch; storm-hail=Storm: Hail Storm"
#   (separate steps with ";" -- in -File mode PowerShell passes the whole -Steps value as ONE string)
#
# Flow: build the shim -> launch the game with it (capturing nothing) -> you get into training mode
# -> for each step: the script tells you what to do, you press ENTER, it records N seconds of GAME
# frames, packs them to <name>.seq, and moves on to the next step.
#
# Each step is "name=what to do". The name becomes the .seq file. Bursts are the same length for
# every step (D3DCAP_BURST is read once by the shim at launch).
#
#   -Seconds N   seconds of match per step (default 3)
#   -Steps       the list; the default below is the current gate work (rotation + flipped poses)
#   -Keep        do not wipe previous captures first
[CmdletBinding()]
param(
    [double]$Seconds = 3,
    [string[]]$Steps = @(
        'sent-rocket=SENTINEL: the diagonal rocket punch (arm fires UP at ~28 deg) -- hit Storm with it',
        'storm-down=STORM knocked DOWN: any hard knockdown so she lands and lies on the floor',
        'storm-hail=STORM: Hail Storm super (the 180-deg bolts), Sentinel standing in it',
        'sent-hsf=SENTINEL: Hyper Sentinel Force (the drone super)',
        'storm-lightning=STORM: lightning attack + lightning storm super'
    ),
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$here   = $PSScriptRoot
$capDir = Join-Path $env:TEMP 'rrcap'
$log    = Join-Path $capDir 'd3dcap.log'
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
$env:D3DCAP_MANUAL = '1'
$env:D3DCAP_BURST  = "$burst"

Say "[build] compiling d3dcap..."
$g = Game
if ($g) { Stop-Process -Id $g.Id -Force; while (Game) { Start-Sleep -Milliseconds 300 }; Start-Sleep -Seconds 2 }
$out = & cmd /c "`"$(Join-Path $here 'build.bat')`"" 2>&1
if ($LASTEXITCODE -ne 0 -or ($out | Select-String -Quiet 'BUILD FAILED|fatal error')) {
    $out | Select-String -Pattern 'error|BUILD' | ForEach-Object { Say "  $_" Red }
    exit 1
}
Say "[build] OK" Green

Say "[game] launching SUSPENDED (hooked before any game code runs)..."
$r = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'launch_suspended.ps1') 2>&1
if (-not ($r -match 'LAUNCHED')) { Say "[game] launch failed: $r" Red; exit 1 }
$deadline = (Get-Date).AddMinutes(2)
while (-not (Game) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
if (-not (Game)) { Say "[game] process did not survive launch" Red; exit 1 }
Say "[inject] injected pre-execution; capture is HELD until a step arms it" Green
Say ""
Rule
Say " GET INTO TRAINING MODE: Sentinel vs Storm (you control whichever the step names)." Cyan
Say " The game runs at FULL SPEED between steps. Each step records $Seconds s of GAME time" Cyan
Say " and the game WILL crawl only while it records." Cyan
Rule
Read-Host " Press ENTER once you are in training mode and both characters are on screen"

# Read new log lines since $pos; returns the text.
function LogSince([ref]$pos) {
    if (-not (Test-Path $log)) { return '' }
    $len = (Get-Item $log).Length
    if ($len -le $pos.Value) { return '' }
    $fs = [IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
    $null = $fs.Seek($pos.Value, 'Begin')
    $sr = New-Object IO.StreamReader($fs)
    $txt = $sr.ReadToEnd()
    $sr.Close(); $fs.Close(); $pos.Value = $len
    return $txt
}

# `powershell -File x.ps1 -Steps "a=..","b=.."` hands the script ONE string with the comma inside it
# (no array parsing in -File mode), so accept ';' as the separator and split a lone element on it.
if ($Steps.Count -eq 1 -and $Steps[0] -match ';') { $Steps = $Steps[0] -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
$results = @()
$logPos = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }
$n = 0
foreach ($step in $Steps) {
    $n++
    $name, $what = $step -split '=', 2
    if (-not $what) { $what = $name }
    Say ""
    Rule
    Say (" STEP $n/$($Steps.Count)  [$name]") Cyan
    Say ("   " + $what) Yellow
    Say ("   Recording starts the moment you press ENTER and runs for $Seconds s of game time.") Gray
    Say ("   Start the move right after ENTER; the whole thing must happen inside the window.") Gray
    Rule
    Read-Host " Press ENTER to record this step"
    $null = LogSince ([ref]$logPos)                       # discard anything older
    New-Item -ItemType File -Force (Join-Path $capDir 'ARM') | Out-Null
    Say "[burst] armed - recording..." Green
    $first = -1; $count = 0; $cost = ''
    $stop = (Get-Date).AddMinutes(10)
    while ((Get-Date) -lt $stop) {
        Start-Sleep -Milliseconds 700
        if (-not (Game)) { Say "[game] exited" Red; break }
        $txt = LogSince ([ref]$logPos)
        if ($txt) {
            foreach ($line in ($txt -split "`r?`n")) {
                if ($line -match '\[burst\] (\d+)/(\d+) frames') { Say "  $line" DarkGray }
                elseif ($line -match '\[burst\] abandoned') { Say "  $line  (not in a match yet -- keep going, it retries)" DarkYellow }
                elseif ($line -match '\[burst\] COMPLETE: (\d+) consecutive frames from (\d+)(.*)') {
                    $count = [int]$Matches[1]; $first = [int]$Matches[2]; $cost = $Matches[3]
                }
            }
        }
        if ($first -ge 0) { break }
    }
    if ($first -lt 0) { Say "[burst] step [$name] did not complete -- skipping it" Red; continue }
    $last = $first + $count - 1
    Say "[burst] $count frames $first..$last$cost" Green
    # let the writer thread drain before packing reads the files
    Start-Sleep -Seconds 2
    $seq = Join-Path $here "replay\cap_$name.seq"
    Say "[pack] $first..$last -> $(Split-Path $seq -Leaf)"
    & python (Join-Path $here 'replay\pack_sequence.py') $first $last -o $seq
    if ($LASTEXITCODE -ne 0) { Say "[pack] FAILED for [$name] (exit $LASTEXITCODE) -- frames are still in $capDir" Red }
    $results += [pscustomobject]@{ step = $name; first = $first; last = $last; seq = (Split-Path $seq -Leaf); packed = ($LASTEXITCODE -eq 0) }
}

Say ""
Rule
Say " DONE" Cyan
Rule
$results | Format-Table -AutoSize | Out-String | ForEach-Object { Say $_ }
$results | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $capDir 'steps.json')
Say "[next] python $(Join-Path $here 'replay\serve.py')   then   http://localhost:8099/player.html" Green
Say "[gate] python $(Join-Path $here 'replay\v3gate.py') $capDir\..\  -- see replay\v3gate.py for the per-step gate" Green
