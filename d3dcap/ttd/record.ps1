<#
record.ps1 -- attach Microsoft TTD to the running Steam MvC2 process for N seconds, stop cleanly, and snapshot
              the live memory images before and after (dump_live.py) so the trace can be replayed whole.

  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\record.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\record.ps1 -Seconds 3            # default 3
  powershell -NoProfile -ExecutionPolicy Bypass -File ...\record.ps1 -Proc notepad -NoDump  # synthetic pipeline test

TTD recording REQUIRES administrator rights (verified: non-elevated attach fails with 0x80070005 "Administrative
privileges are required"). This script relaunches itself elevated (one UAC prompt) and the elevated child does
the work; the parent waits and tails the child's log.

  * OFFLINE ONLY (versus / training). Recording slows the game roughly 10x; an online GGPO session would
    desync and disconnect. The script refuses if a GGPO session pointer is live (meta.json ggpo_session != 0).
  * Output: <OutRoot>\<yyyyMMdd-HHmmss>\  (default C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs, gitignored)
        pre\   dump_live.py snapshot taken right before attach   (meta.json, blk.bin, dcram.bin, ctx.bin, exe_image.bin ...)
        post\  snapshot right after stop
        *.run  the TTD trace (multi-GB), *.out the recorder log, record.log this script's log
  * -ModuleOnly (default on): `-module <exe>` so TTD records only the game module (and what it calls);
    threads that never enter the exe (audio, Steam) are skipped -> smaller, faster. -AllModules disables it.
  * Recorder binary: the winget package Microsoft.TimeTravelDebugging (ttd.exe alias in %LOCALAPPDATA%\Microsoft\WindowsApps);
    the WinDbg package (Microsoft.WinDbg) carries the same recorder under amd64\ttd\TTD.exe.
#>
param(
    [int]$Seconds = 3,
    [string]$Proc = 'MarvelVsCapcomFightingCollection',
    [string]$OutRoot = (Join-Path $PSScriptRoot 'runs'),
    [string]$RunDir = '',
    [switch]$AllModules,
    [switch]$NoDump,
    [switch]$Elevated,
    [int]$AttachTimeout = 120,
    [int]$TargetPid = 0
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

function Find-Ttd {
    $c = @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\ttd.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\Microsoft.TimeTravelDebugging_8wekyb3d8bbwe\ttd.exe')
    )
    foreach ($p in $c) { if (Test-Path $p) { return $p } }
    $pk = Get-ChildItem 'C:\Program Files\WindowsApps' -Directory -Filter 'Microsoft.WinDbg_*_x64*' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pk) { $p = Join-Path $pk.FullName 'amd64\ttd\TTD.exe'; if (Test-Path $p) { return $p } }
    throw 'ttd.exe not found. Install: winget install --id Microsoft.TimeTravelDebugging --exact --accept-package-agreements --accept-source-agreements'
}
function Find-Python {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py -or $py -match 'WindowsApps') { $py = 'C:\Python313\python.exe' }   # the Store alias is not a python
    return $py
}
function Is-Admin { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }

if (-not $RunDir) { $RunDir = Join-Path $OutRoot (Get-Date -Format 'yyyyMMdd-HHmmss') }
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$log = Join-Path $RunDir 'record.log'
function Say([string]$m) { $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss.fff'), $m; Write-Host $line; Add-Content -Path $log -Value $line }

# ---------------------------------------------------------------- parent: elevate and wait
if (-not $Elevated -and -not (Is-Admin)) {
    $g = if ($TargetPid) { Get-Process -Id $TargetPid -ErrorAction SilentlyContinue } else { Get-Process $Proc -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if (-not $g) { Say "[record] process '$Proc' is not running -- start the game, get into an OFFLINE match, then rerun"; exit 1 }
    Say "[record] target $Proc pid $($g.Id); elevating (accept the UAC prompt) ..."
    $args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"",'-Elevated','-Seconds',$Seconds,'-Proc',$Proc,'-RunDir',"`"$RunDir`"",'-AttachTimeout',$AttachTimeout)
    if ($AllModules) { $args += '-AllModules' }
    if ($NoDump) { $args += '-NoDump' }
    if ($TargetPid) { $args += @('-TargetPid', $TargetPid) }
    $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $args -Verb RunAs -PassThru
    $child.WaitForExit()
    Say "[record] elevated child exited with code $($child.ExitCode)"
    if (Test-Path $log) { Get-Content $log | Select-Object -Last 25 }
    $run = Get-ChildItem $RunDir -Filter '*.run' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($run) {
        Say ("[record] TRACE: {0} ({1:N0} MB)" -f $run.FullName, ($run.Length/1MB))
        Say "[record] next: python `"$here\extract.py`" --run `"$RunDir`""
    } else { Say "[record] no .run produced -- see $log"; exit 1 }
    exit $child.ExitCode
}

# ---------------------------------------------------------------- elevated child: the actual recording
try {
    $ttd = Find-Ttd
    $py  = Find-Python
    Say "[record] ttd = $ttd"
    $g = if ($TargetPid) { Get-Process -Id $TargetPid -ErrorAction SilentlyContinue } else { Get-Process $Proc -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if (-not $g) { throw "process '$Proc' is not running" }
    $procPid = $g.Id
    $exeName = [IO.Path]::GetFileName($g.Path)
    Say "[record] target $exeName pid $procPid base 0x$($g.MainModule.BaseAddress.ToInt64().ToString('X'))"

    if (-not $NoDump) {
        Say "[record] pre-snapshot (dump_live.py) ..."
        & $py (Join-Path $here 'dump_live.py') --out (Join-Path $RunDir 'pre') --pid $procPid 2>&1 | ForEach-Object { Add-Content $log $_ }
        $meta = Get-Content (Join-Path $RunDir 'pre\meta.json') -Raw | ConvertFrom-Json
        Say "[record] pre: blk=$($meta.blk) dcram=$($meta.dcram) clock=$($meta.clock_value) ggpo_session=$($meta.ggpo_session) scene=$($meta.scene_id)"
        if ($meta.ggpo_session -ne '0x0') { throw "GGPO session is LIVE ($($meta.ggpo_session)) -- refusing to record an online match" }
        if ($meta.clock_value -eq $meta.clock_value_after) { Say "[record] WARNING: frame clock did not advance during the snapshot -- are you in a running match (not paused / not a menu)?" }
    }

    $ttdArgs = @('-accepteula','-noUI','-out',"`"$RunDir`"")
    if (-not $AllModules) { $ttdArgs += @('-module', $exeName) }
    $ttdArgs += @('-attach', $procPid)
    Say "[record] $ttd $($ttdArgs -join ' ')"
    $so = Join-Path $RunDir 'ttd_stdout.txt'; $se = Join-Path $RunDir 'ttd_stderr.txt'
    $rec = Start-Process -FilePath $ttd -ArgumentList $ttdArgs -PassThru -NoNewWindow -RedirectStandardOutput $so -RedirectStandardError $se

    # wait for the .run to appear (attach + injection), then count the requested seconds from there
    $t0 = Get-Date; $run = $null
    while (-not $run -and ((Get-Date) - $t0).TotalSeconds -lt $AttachTimeout) {
        Start-Sleep -Milliseconds 200
        $run = Get-ChildItem $RunDir -Filter '*.run' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($rec.HasExited) { break }
    }
    if (-not $run) { throw "no .run file appeared within $AttachTimeout s (stderr: $(Get-Content $se -Raw))" }
    Say "[record] RECORDING $($run.Name) -- $Seconds s of game time (the game is ~10x slower under TTD)"
    Start-Sleep -Seconds $Seconds
    Say "[record] stop"
    & $ttd -accepteula -stop $procPid 2>&1 | ForEach-Object { Add-Content $log $_ }
    if (-not $rec.WaitForExit(120000)) { Say "[record] WARNING: recorder did not exit in 120 s" }
    Say "[record] recorder exit code $($rec.ExitCode)"
    Get-Content $so -ErrorAction SilentlyContinue | ForEach-Object { Add-Content $log ("  ttd> " + $_) }
    Get-Content $se -ErrorAction SilentlyContinue | ForEach-Object { Add-Content $log ("  ttd! " + $_) }

    if (-not $NoDump) {
        Say "[record] post-snapshot ..."
        & $py (Join-Path $here 'dump_live.py') --out (Join-Path $RunDir 'post') --pid $procPid --no-exe-image 2>&1 | ForEach-Object { Add-Content $log $_ }
    }
    $run = Get-ChildItem $RunDir -Filter '*.run' | Select-Object -First 1
    Say ("[record] DONE {0} ({1:N0} MB)" -f $run.FullName, ($run.Length/1MB))
    exit 0
} catch {
    Say "[record] ERROR: $($_.Exception.Message)"
    exit 2
}
