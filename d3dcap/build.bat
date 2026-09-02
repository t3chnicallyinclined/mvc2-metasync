@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 ( echo vcvars64 failed & exit /b 1 )
cd /d "%~dp0"
set VCPKG=C:\Users\trist\projects\vcpkg\installed\x64-windows-static
cl /nologo /LD /O2 /MT /EHsc /std:c++17 /W3 /I"%VCPKG%\include" dllmain.cpp /Fe:d3dcap.dll /link /LIBPATH:"%VCPKG%\lib" minhook.x64.lib d3d11.lib dxgi.lib user32.lib
if errorlevel 1 ( echo BUILD FAILED & exit /b 1 )
echo BUILD OK: %~dp0d3dcap.dll
