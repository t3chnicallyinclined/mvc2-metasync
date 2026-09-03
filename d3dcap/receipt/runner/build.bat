@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 ( echo vcvars64 failed & exit /b 1 )
cd /d "%~dp0"
rem A normal /DYNAMICBASE /HIGHENTROPYVA exe: it must NOT be linked at 0x140000000 (the game image's link base) and must
rem leave the anchor's 256 MiB arena free; both are asserted at start-up (rr_runner.cpp main, step 0).
cl /nologo /O2 /MT /EHsc /std:c++17 /W3 rr_runner.cpp /Fe:rr_runner.exe /link /DYNAMICBASE /HIGHENTROPYVA psapi.lib
if errorlevel 1 ( echo BUILD FAILED & exit /b 1 )
echo BUILD OK: %~dp0rr_runner.exe
