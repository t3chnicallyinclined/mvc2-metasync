# synthetic_test.ps1 -- prove the TTD pipeline end to end WITHOUT the game:
#   synthetic_target.py (fake blk + frame clock) -> record.ps1 (elevated TTD attach, N s) -> extract.py --synthetic
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\synthetic_test.ps1 [-Seconds 2] [-Frames 3]
param([int]$Seconds = 2, [int]$Frames = 3, [int]$FirstFrame = 5)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py -or $py -match 'WindowsApps') { $py = 'C:\Python313\python.exe' }
$run = Join-Path $here ('runs\synthetic-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $run | Out-Null
$tgt = Start-Process -FilePath $py -ArgumentList @((Join-Path $here 'synthetic_target.py'), '--out', $run, '--ticks', '3000') -PassThru -NoNewWindow -RedirectStandardOutput (Join-Path $run 'target_stdout.txt')
$cfg = Join-Path $run 'synthetic_cfg.json'
$t0 = Get-Date
while (-not (Test-Path $cfg) -and ((Get-Date) - $t0).TotalSeconds -lt 20) { Start-Sleep -Milliseconds 200 }
if (-not (Test-Path $cfg)) { throw 'synthetic target did not write its cfg' }
Write-Host "[synthetic] target pid $($tgt.Id); cfg $cfg"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'record.ps1') -TargetPid $tgt.Id -Proc python -NoDump -AllModules -Seconds $Seconds -RunDir $run
$rc = $LASTEXITCODE
Stop-Process -Id $tgt.Id -Force -ErrorAction SilentlyContinue
if ($rc -ne 0) { throw "record.ps1 failed ($rc)" }
& $py (Join-Path $here 'extract.py') --run $run --synthetic $cfg --frames $Frames --first-frame $FirstFrame
Write-Host "[synthetic] extract exit $LASTEXITCODE; outputs in $run\extract"
