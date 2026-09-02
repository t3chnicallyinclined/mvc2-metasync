# RETRO RECEIPTS - Path B: inject d3dcap.dll into the running game.
# Technique ported verbatim from the SHIPPING tray injector (src-tauri/src/sync.rs:4250-4278):
# OpenProcess(0x43A) -> VirtualAllocEx -> WriteProcessMemory -> CreateRemoteThread(LoadLibraryW).
# That path is proven in production against this exact (DRM'd) binary.

$ErrorActionPreference = 'Stop'
$dll = Join-Path $PSScriptRoot 'd3dcap.dll'
if (-not (Test-Path $dll)) { Write-Host "MISSING: $dll  (run build.bat first)"; exit 1 }

$proc = Get-Process MarvelVsCapcomFightingCollection -ErrorAction SilentlyContinue
if (-not $proc) { Write-Host "GAME_NOT_RUNNING"; exit 1 }
$pid2 = $proc.Id

$sig = @'
using System; using System.Runtime.InteropServices;
public class Inj {
 [DllImport("kernel32")] public static extern IntPtr OpenProcess(uint a,bool b,int p);
 [DllImport("kernel32")] public static extern IntPtr VirtualAllocEx(IntPtr h,IntPtr a,uint s,uint t,uint p);
 [DllImport("kernel32")] public static extern bool WriteProcessMemory(IntPtr h,IntPtr a,byte[] b,uint s,out uint w);
 [DllImport("kernel32")] public static extern IntPtr GetModuleHandle(string m);
 [DllImport("kernel32")] public static extern IntPtr GetProcAddress(IntPtr h,string n);
 [DllImport("kernel32")] public static extern IntPtr CreateRemoteThread(IntPtr h,IntPtr a,uint s,IntPtr f,IntPtr p,uint fl,IntPtr t);
 [DllImport("kernel32")] public static extern uint WaitForSingleObject(IntPtr h,uint ms);
}
'@
Add-Type $sig

$h = [Inj]::OpenProcess(0x43A, $false, $pid2)
if ($h -eq [IntPtr]::Zero) { Write-Host "OPENPROCESS_FAILED"; exit 1 }
$bytes = [System.Text.Encoding]::Unicode.GetBytes($dll + "`0")
$mem = [Inj]::VirtualAllocEx($h, [IntPtr]::Zero, [uint32]$bytes.Length, 0x3000, 0x40)
[Inj]::WriteProcessMemory($h, $mem, $bytes, [uint32]$bytes.Length, [ref]([uint32]0)) | Out-Null
$k = [Inj]::GetModuleHandle("kernel32.dll")
$load = [Inj]::GetProcAddress($k, "LoadLibraryW")
$t = [Inj]::CreateRemoteThread($h, [IntPtr]::Zero, 0, $load, $mem, 0, [IntPtr]::Zero)
if ($t -eq [IntPtr]::Zero) { Write-Host "CREATETHREAD_FAILED"; exit 1 }
[Inj]::WaitForSingleObject($t, 5000) | Out-Null

Write-Host "INJECTED  pid=$pid2"
Write-Host "log:      $env:TEMP\rrcap\d3dcap.log"
Write-Host "captures: $env:TEMP\rrcap\frame_<n>.ndjson"
Write-Host ""
Write-Host "Now: get into a real VS match, then press F9 in the game to capture one frame."
