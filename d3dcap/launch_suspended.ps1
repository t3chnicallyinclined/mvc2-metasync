# RETRO RECEIPTS - Path B: launch the game SUSPENDED, inject, then resume.
#
# Why this exists: the game creates its D3D11 device very early in startup. Injecting after the
# Windows loader settles is already too late (the creation hook never fires, so shader and
# input-layout bytecode -- which can ONLY be captured at CreateVertexShader / CreateInputLayout time
# -- is unrecoverable). Injecting the instant the process appears is EARLIER but crashes it:
# LoadLibraryW via CreateRemoteThread while the loader is initialising deadlocks the process.
#
# CREATE_SUSPENDED removes the race entirely. The process exists but has executed no instruction, so
# we inject into a quiet process and only then let it run. Steam must already be running; SteamAppId
# is set so the DRM is satisfied by a direct launch.
#
# Exits 0 and prints LAUNCHED <pid> on success.

param(
    [string]$Exe = "C:\Program Files (x86)\Steam\steamapps\common\MARVEL vs. CAPCOM Fighting Collection\MarvelVsCapcomFightingCollection.exe",
    [int]$AppId = 2634890
)

$ErrorActionPreference = 'Stop'
$dll = Join-Path $PSScriptRoot 'd3dcap.dll'
if (-not (Test-Path $dll)) { Write-Host "MISSING $dll"; exit 1 }
if (-not (Test-Path $Exe)) { Write-Host "MISSING $Exe"; exit 1 }

$sig = @'
using System;
using System.Runtime.InteropServices;

public class Susp {
    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_INFORMATION { public IntPtr hProcess; public IntPtr hThread; public uint dwProcessId; public uint dwThreadId; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct STARTUPINFO {
        public uint cb; public string lpReserved; public string lpDesktop; public string lpTitle;
        public uint dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public ushort wShowWindow; public ushort cbReserved2; public IntPtr lpReserved2;
        public IntPtr hStdInput, hStdOutput, hStdError;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CreateProcess(string app, string cmd, IntPtr pa, IntPtr ta,
        bool inherit, uint flags, IntPtr env, string curDir, ref STARTUPINFO si, out PROCESS_INFORMATION pi);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr VirtualAllocEx(IntPtr h, IntPtr a, uint size, uint type, uint protect);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool WriteProcessMemory(IntPtr h, IntPtr a, byte[] b, uint size, out uint written);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    public static extern IntPtr GetModuleHandle(string m);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    public static extern IntPtr GetProcAddress(IntPtr h, string n);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr CreateRemoteThread(IntPtr h, IntPtr a, uint stack, IntPtr fn, IntPtr param, uint flags, IntPtr tid);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint WaitForSingleObject(IntPtr h, uint ms);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint ResumeThread(IntPtr h);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool TerminateProcess(IntPtr h, uint code);
}
'@
Add-Type $sig

$env:SteamAppId = "$AppId"
$env:SteamGameId = "$AppId"

$si = New-Object Susp+STARTUPINFO
$si.cb = [Runtime.InteropServices.Marshal]::SizeOf($si)
$pi = New-Object Susp+PROCESS_INFORMATION
$workDir = Split-Path $Exe -Parent

# 0x00000004 = CREATE_SUSPENDED
if (-not [Susp]::CreateProcess($Exe, $null, [IntPtr]::Zero, [IntPtr]::Zero, $false, 0x4, [IntPtr]::Zero, $workDir, [ref]$si, [ref]$pi)) {
    Write-Host "CREATEPROCESS_FAILED $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    exit 1
}

try {
    $bytes = [Text.Encoding]::Unicode.GetBytes($dll + "`0")
    # 0x3000 = MEM_COMMIT|MEM_RESERVE, 0x40 = PAGE_EXECUTE_READWRITE
    $mem = [Susp]::VirtualAllocEx($pi.hProcess, [IntPtr]::Zero, [uint32]$bytes.Length, 0x3000, 0x40)
    if ($mem -eq [IntPtr]::Zero) { throw "VirtualAllocEx failed" }
    $written = 0
    [void][Susp]::WriteProcessMemory($pi.hProcess, $mem, $bytes, [uint32]$bytes.Length, [ref]$written)

    $k32 = [Susp]::GetModuleHandle("kernel32.dll")
    $load = [Susp]::GetProcAddress($k32, "LoadLibraryW")
    $t = [Susp]::CreateRemoteThread($pi.hProcess, [IntPtr]::Zero, 0, $load, $mem, 0, [IntPtr]::Zero)
    if ($t -eq [IntPtr]::Zero) { throw "CreateRemoteThread failed $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }
    [void][Susp]::WaitForSingleObject($t, 10000)
} catch {
    Write-Host "INJECT_FAILED $_"
    [void][Susp]::TerminateProcess($pi.hProcess, 1)
    exit 1
}

# Let it run, now that we are already inside and hooked.
[void][Susp]::ResumeThread($pi.hThread)
Write-Host "LAUNCHED $($pi.dwProcessId)"
exit 0
