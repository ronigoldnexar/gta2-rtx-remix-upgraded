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
cl /nologo /std:c++17 /EHsc /O2 /W3 /MT /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS ^
   /I deps\bridge_api /I deps\imgui ^
   /LD /Fe:build\gta2dx9.dll /Fo:build\ ^
   src\dllmain.cpp src\world_view.cpp src\regress_cam.cpp src\log.cpp src\texture_store.cpp src\overlay.cpp ^
   src\live_geometry.cpp src\ground.cpp src\remix_api.cpp src\remix_lights.cpp src\debug_overlay.cpp ^
   src\synthetic_lights.cpp src\settings.cpp src\frame_limiter.cpp src\frame_log.cpp src\time_of_day.cpp ^
   src\intro_movie.cpp src\hud_pass.cpp src\hud3d.cpp src\gibs.cpp src\light_bench.cpp src\progress_probe.cpp src\game_save.cpp src\voice_over.cpp src\cache_warmup.cpp src\plugin_d3d6.cpp src\view_modes.cpp src\eye_collision.cpp src\model_store.cpp src\identity.cpp src\car_bodies.cpp src\cab_interior.cpp src\cockpit_mode.cpp src\vehicle_fx.cpp src\city_ai.cpp src\audio3d.cpp src\beats.cpp src\boarding.cpp src\density.cpp src\explosion_fx.cpp src\ragdoll.cpp src\map_objects.cpp src\visuals.cpp src\weather.cpp build\plugin_slot.obj ^
   deps\imgui\imgui.cpp deps\imgui\imgui_draw.cpp deps\imgui\imgui_tables.cpp ^
   deps\imgui\imgui_widgets.cpp deps\imgui\backends\imgui_impl_dx9.cpp ^
   deps\imgui\backends\imgui_impl_win32.cpp ^
   ..\src\camera.cpp ..\src\gta2_map.cpp ..\src\gta2_style.cpp ..\src\renderer.cpp ..\src\world_mesh.cpp ..\src\post_fx.cpp ..\src\sky.cpp ..\src\weather_fx.cpp ^
   /link /DEF:gta2dx9.def user32.lib psapi.lib gdi32.lib dwmapi.lib winmm.lib || exit /b 1

echo Built build\gta2dx9.dll
