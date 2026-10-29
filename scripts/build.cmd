@echo off
REM Build the ZooTogether DLL (openzt fork) for 32-bit Zoo Tycoon.
REM Runs cargo inside a VS x86 environment; LuaJIT's msvcbuild needs x86 cl on PATH and
REM needs to run tools from the current directory (Claude Code / some shells set
REM NoDefaultCurrentDirectoryInExePath, which breaks it).
setlocal
set NoDefaultCurrentDirectoryInExePath=
for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath`) do set VSROOT=%%i
call "%VSROOT%\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1
cd /d "%~dp0..\vendor\openzt" || exit /b 1
cargo build --manifest-path openzt-dll/Cargo.toml --lib --target=i686-pc-windows-msvc --release --features "command-console coop" %*
