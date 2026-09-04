@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 ( echo vcvars64 failed & exit /b 1 )
cd /d "%~dp0"
cl /nologo /O2 /MT /EHsc /std:c++17 /W3 sg_bench.cpp /Fe:sg_bench.exe
if errorlevel 1 ( echo BUILD FAILED & exit /b 1 )
echo BUILD OK: %~dp0sg_bench.exe
