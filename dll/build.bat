@echo off
setlocal
rem Paths below are relative, so run from this script's own directory whatever
rem the caller's happens to be.
cd /d "%~dp0" || exit /b 1

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -property installationPath`) do set "VSPATH=%%i"
if not defined VSPATH (
    echo Visual Studio not found.
    exit /b 1
)
rem x86: gta2.exe is a 32-bit process, and the naked thunks are x86 inline asm.
call "%VSPATH%\VC\Auxiliary\Build\vcvars32.bat" >nul || exit /b 1

if not exist build mkdir build
rem plugin_slot.asm is a block of code space at a fixed offset; see the file.
ml /nologo /c /Fo build\plugin_slot.obj src\plugin_slot.asm >nul || exit /b 1
rem The world renderer, mesh builder and file loaders live in ..\src.
rem No d3d9.lib on the link line: the renderer resolves Direct3DCreate9 with
rem LoadLibrary so the RTX Remix bridge client does not start under the loader lock.
rem deps\bridge_api holds the RTX Remix API headers. They must match the deployed
rem Remix runtime: remixapi_LightInfo has gained fields over time and the struct
rem is serialised across the 32-bit bridge, so a mismatch corrupts silently
rem instead of failing to compile. deps\imgui is the F4 menu.
rem Every source by wildcard, as the Makefile does: a hand-kept list fell behind (car_glass,
rem prop_collision, thread_watch, weapon_rig, water) and no longer linked.
rem /Zi + /DEBUG /OPT:REF /OPT:ICF: a .pdb beside the DLL with the release code layout kept;
rem /MAP: build\gta2dx9.map, so an offset in a crash report (gta2dx9.dll+0x...) names its
rem function with nothing but a text editor (FIX-STABILITY-1, owner-5090 crashes). Ship both
rem beside the DLL; they are what the next owner log is read against.
cl /nologo /std:c++17 /EHsc /O2 /Zi /W3 /MT /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS ^
   /I deps\bridge_api /I deps\imgui ^
   /LD /Fe:build\gta2dx9.dll /Fo:build\ /Fd:build\gta2dx9_cl.pdb ^
   src\*.cpp build\plugin_slot.obj ^
   deps\imgui\imgui.cpp deps\imgui\imgui_draw.cpp deps\imgui\imgui_tables.cpp ^
   deps\imgui\imgui_widgets.cpp deps\imgui\backends\imgui_impl_dx9.cpp ^
   deps\imgui\backends\imgui_impl_win32.cpp ^
   ..\src\*.cpp ^
   /link /DEF:gta2dx9.def /DEBUG /OPT:REF /OPT:ICF /PDB:build\gta2dx9.pdb /MAP:build\gta2dx9.map ^
   user32.lib psapi.lib gdi32.lib dwmapi.lib winmm.lib ole32.lib shell32.lib advapi32.lib uuid.lib || exit /b 1

echo Built build\gta2dx9.dll, build\gta2dx9.map and build\gta2dx9.pdb
