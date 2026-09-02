# RETRO RECEIPTS - Path B: ONE-PASS collection.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File collect.ps1
#
# Does everything in a single run and stops on its own:
#   build -> launch -> inject the instant the process appears -> wait while you play ->
#   detect the first COMPLETE gameplay frame -> print the full analysis -> exit.
#
# "Complete" is not a guess. decode_verts.py exits 0 only when, for that frame:
#   * the disjointness gate passes (the VB snapshot is valid for every draw), AND
#   * every input layout / VS / PS the frame references was captured at creation time, AND
#   * the vertex snapshot exists and decodes against the authoritative layout.
# Anything less and it keeps waiting rather than handing you a half-capture.
#
#   -Analyze     skip launching; just analyse whatever is already in %TEMP%\rrcap
#   -Keep        do not wipe previous captures first
#   -Minutes N   give up after N minutes of play (default 10)
#   -Seconds N   record N seconds of MATCH (N*60 consecutive frames) -- see -Burst
#   -Burst N     record N CONSECUTIVE frames instead of one, then pack them into a playable
#                sequence. This is what turns a still into a replay. 90 frames is ~1.5 seconds of
#                match at 60 fps. The game WILL hitch while the burst records -- it is copying every
#                dirty texture and both index/vertex buffers every frame -- so start the burst on the
#                action you want, not before it.

[CmdletBinding()]
param(
    [switch]$Analyze,
    [switch]$Keep,
    [int]$Minutes = 10,
    [int]$Burst = 0,
    [double]$Seconds = 0
)

# -Seconds is the honest unit: the capture records GAME frames at 60 fps, so N seconds of match is
# N*60 frames however slowly the game is actually running while it records.
if ($Seconds -gt 0) { $Burst = [int][math]::Round($Seconds * 60) }

$ErrorActionPreference = 'Stop'
$here   = $PSScriptRoot
$capDir = Join-Path $env:TEMP 'rrcap'
$log    = Join-Path $capDir 'd3dcap.log'
$decode = Join-Path $here 'decode_verts.py'
$summ   = Join-Path $here 'summarize.py'
$APPID  = 2634890
$PROC   = 'MarvelVsCapcomFightingCollection'

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Game { Get-Process $PROC -ErrorAction SilentlyContinue | Select-Object -First 1 }

function Analyze-Best {
    # Rank by DISTINCT TEXTURE COUNT, not recency. A super or an assist-heavy frame binds ~3x the
    # sprite pages of a neutral standing frame (measured: neutral ~96, mid-combo ~137, super ~298),
    # and the effect-heavy case is precisely what Path A cannot render -- so it is the frame worth
    # keeping. A frame only qualifies if it also passes the in-match, coverage and disjointness gates.
    $best = $null; $bestScore = 0
    $cands = Get-ChildItem "$capDir\frame_*.ndjson" -ErrorAction SilentlyContinue |
             Where-Object { $_.Length -gt 0 }
    foreach ($f in $cands) {
        $n = (Get-Content $f.FullName | Measure-Object -Line).Lines
        if ($n -lt 300) { continue }
        $id = $f.BaseName -replace 'frame_', ''
        $score = 0
        try { $score = [int](& python $decode $id --score 2>$null | Select-Object -Last 1) } catch { $score = 0 }
        if ($score -le $bestScore) { continue }
        & python $decode $id | Out-Null            # full gates: coverage + snapshot + disjointness
        if ($LASTEXITCODE -eq 0) { $best = $id; $bestScore = $score }
    }
    if ($best) { Say "  (best in-match frame: $best, $bestScore distinct sprite pages)" DarkGray }
    return $best
}

if (-not $Analyze) {
    if (-not $Keep -and (Test-Path $capDir)) {
        Say "[prep] clearing previous captures"
        Remove-Item "$capDir\*" -Force -ErrorAction SilentlyContinue
    }

    # The shim reads this before it installs any hook; the launched process inherits it.
    if ($Burst -gt 1) {
        $env:D3DCAP_BURST = "$Burst"
        Say "[burst] recording $Burst CONSECUTIVE frames per arm" Cyan
    } else {
        Remove-Item Env:\D3DCAP_BURST -ErrorAction SilentlyContinue
    }

    Say "[build] compiling d3dcap..."
    $g = Game
    if ($g) { Stop-Process -Id $g.Id -Force; while (Game) { Start-Sleep -Milliseconds 300 }; Start-Sleep -Seconds 2 }
    $out = & cmd /c "`"$(Join-Path $here 'build.bat')`"" 2>&1
    if ($LASTEXITCODE -ne 0 -or ($out | Select-String -Quiet 'BUILD FAILED')) {
        $out | Select-String -Pattern 'error|BUILD' | ForEach-Object { Say "  $_" Red }
        exit 1
    }
    Say "[build] OK" Green

    # PRIMARY: launch SUSPENDED and inject before a single instruction runs. The game creates its
    # D3D11 device very early, so there is no safe post-launch window -- injecting after the loader
    # settles misses device creation (no shader/layout bytecode, which is unrecoverable), and
    # injecting sooner deadlocks the loader. CREATE_SUSPENDED removes the race entirely.
    Say "[game] launching SUSPENDED (so we are hooked before any game code runs)..."
    $r = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'launch_suspended.ps1') 2>&1
    $suspOk = ($r -match 'LAUNCHED')
    if ($suspOk) {
        Say "[game] $($r | Select-String 'LAUNCHED')" Green
        Say "[inject] injected pre-execution - the creation hook cannot be missed" Green
    } else {
        # Steam DRM may refuse a direct launch. Fall back to the Steam path; coverage may be partial,
        # and the DLL says so explicitly in the log rather than failing silently.
        Say "[game] suspended launch unavailable: $r" Yellow
        Say "[game] falling back to Steam launch (shader coverage may be incomplete)" Yellow
        Start-Process "steam://rungameid/$APPID"
        $deadline = (Get-Date).AddMinutes(3)
        while (-not (Game) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 100 }
        if (-not (Game)) { Say "[game] never appeared" Red; exit 1 }
        $settleBy = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $settleBy) {
            Start-Sleep -Milliseconds 250
            $g = Game
            if (-not $g) { continue }
            try { $g.Refresh(); if (@($g.Modules).Count -ge 40) { break } } catch { }
        }
        $ok = $false
        for ($try = 1; $try -le 40; $try++) {
            $r2 = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'inject.ps1') 2>&1
            if ($r2 -match 'INJECTED') { Say "[inject] OK on attempt $try" Green; $ok = $true; break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $ok) { Say "[inject] FAILED" Red; exit 1 }
    }

    $deadline = (Get-Date).AddMinutes(2)
    while (-not (Game) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if (-not (Game)) { Say "[game] process did not survive launch" Red; exit 1 }

    Say ""
    Say "==============================================================================" Cyan
    if ($Burst -gt 1) {
        Say " NOW: go into MvC2 -> TRAINING and get to the action you want to replay." Cyan
        Say " It retries every second until a frame lands IN A MATCH, then records" Cyan
        Say " $Burst CONSECUTIVE frames = $([math]::Round($Burst / 60.0, 1))s of GAME time." Cyan
        Say "" Cyan
        Say " The game will crawl for the whole burst - it is copying every dirty texture and" Cyan
        Say " both buffers every frame. $([math]::Round($Burst / 60.0, 1))s of game time will take a lot longer than that" Cyan
        Say " in real time. Keep playing through it; game frames are what is being counted." Cyan
        Say "==============================================================================" Cyan
        Say ""
    } else {
    Say " NOW: go into MvC2 -> TRAINING, and FIGHT. Land a combo, throw a super." Cyan
    Say " Character select does NOT count - it looks like gameplay to the draw" Cyan
    Say " counter but binds only ~22 textures, so it is rejected automatically." Cyan
    Say " Everything is captured automatically. This window stops by itself as soon" Cyan
    Say " as it has ONE complete gameplay frame, then prints the analysis." Cyan
    Say "==============================================================================" Cyan
    Say ""
    }

    $stop = (Get-Date).AddMinutes($Minutes)
    $script:matchSeen = $false
    $script:extraUntil = (Get-Date)
    $logLen = 0
    $lastNote = ''
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
                    Where-Object { $_ -match '\[cap\]|\[burst\]|\[write\]|\[emit\]|captured at creation|\[mh\]|\[init\]' } |
                    ForEach-Object { Say "  $_" DarkGray }
                $sr.Close(); $fs.Close(); $logLen = $len
            }
        }

        $gp = @(Get-ChildItem "$capDir\frame_*.ndjson" -ErrorAction SilentlyContinue |
                Where-Object { $_.Length -gt 0 -and (Get-Content $_.FullName | Measure-Object -Line).Lines -gt 300 })
        $note = "  ... $($gp.Count) candidate frame(s); waiting for one taken DURING A MATCH"
        if ($note -ne $lastNote) { Say $note; $lastNote = $note }
        if ($gp.Count -ge 1 -and -not $script:matchSeen) {
            $id = Analyze-Best
            if ($id) {
                $script:matchSeen = $true
                # Do not stop at the FIRST match frame -- it is probably neutral. Keep recording so a
                # super or an assist gets captured too, then keep whichever frame is richest.
                $script:extraUntil = (Get-Date).AddSeconds(45)
                Say ""
                Say "[collect] in-match frame found. Recording ~45s more - throw a SUPER and call" Green
                Say "          an ASSIST now; the richest frame is the one that gets kept." Green
                Say ""
            }
        }
        if ($Burst -gt 1) {
            # A burst is CONSECUTIVE frame numbers. Wait until one run of that length exists rather
            # than for a fixed time, so the recording is never cut in half.
            $ids = @(Get-ChildItem "$capDir\frame_*.ndjson" -ErrorAction SilentlyContinue |
                     Where-Object { $_.Length -gt 0 } |
                     ForEach-Object { [int]($_.BaseName -replace 'frame_', '') } | Sort-Object)
            $run = 0; $best = 0; $prev = -99
            foreach ($i in $ids) { if ($i -eq $prev + 1) { $run++ } else { $run = 1 }; $prev = $i
                                   if ($run -gt $best) { $best = $run } }
            if ($best -ge $Burst - 2) { Say "[burst] $best consecutive frames on disk" Green; break }
            if ($best -gt 1) { Say "  ... burst in progress: $best/$Burst frames" DarkGray }
            continue
        }
        if ($script:matchSeen -and (Get-Date) -gt $script:extraUntil) { break }
    }
}

if ($Burst -gt 1) {
    Say ""
    Say "==============================================================================" Cyan
    Say " SEQUENCE" Cyan
    Say "==============================================================================" Cyan
    & python (Join-Path $here 'replay\pack_sequence.py')
    exit $LASTEXITCODE
}

Say ""
Say "==============================================================================" Cyan
Say " ANALYSIS" Cyan
Say "==============================================================================" Cyan
$id = Analyze-Best
if (-not $id) {
    Say ""
    Say "No COMPLETE gameplay frame was captured. Partial results below." Yellow
    $any = Get-ChildItem "$capDir\frame_*.ndjson" -ErrorAction SilentlyContinue |
           Where-Object { $_.Length -gt 0 } | Sort-Object Length -Descending | Select-Object -First 1
    if ($any) {
        & python $decode ($any.BaseName -replace 'frame_', '')
        Say ""
        Say "The line above tells you WHY it is incomplete:" Yellow
        Say "  'no il_... captured'  -> injected after the arcade title loaded; re-run collect.ps1" Yellow
        Say "  'FAILED: ranges overlap' -> that frame was a menu; play a real match" Yellow
        Say "  'MENU or CHARACTER SELECT frame' -> you stopped before the match started" Yellow
    } else {
        Say "No captures at all - did the game reach a match?" Red
    }
    exit 2
}

& python $decode $id
Say ""
& python $summ (Join-Path $capDir "frame_$id.ndjson")
Say ""
$nTex = @(Get-ChildItem "$capDir\tex_*.bin"   -ErrorAction SilentlyContinue).Count
$nCso = @(Get-ChildItem "$capDir\*.cso"       -ErrorAction SilentlyContinue).Count
$nIl  = @(Get-ChildItem "$capDir\il_*.json"   -ErrorAction SilentlyContinue).Count
$nBmp = @(Get-ChildItem "$capDir\shot_*.bmp"  -ErrorAction SilentlyContinue).Count
Say "[assets] $nTex textures, $nCso shaders, $nIl input layouts, $nBmp screenshots" Green
Say "[assets] all in $capDir" Green
