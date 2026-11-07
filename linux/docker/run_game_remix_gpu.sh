#!/usr/bin/env bash
# Inside the container. Sets up the prefix, installs game + mod, starts the
# game on Xvfb, records, screenshots every few seconds, collects logs.
# RTX Remix on an NVIDIA GPU: the patched Wine 10 image (gta2-wine2510) run with
# the NVIDIA container runtime, whose Vulkan ICD the 64-bit Remix server uses.
#   docker run --gpus '"device=7"' -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility ... gta2-wine2510 \
#       bash /work/run_game_remix_gpu.sh <seconds> [keys script]
# TREX_PATCHED=1 uses the lavapipe-patched .trex/d3d9.dll (not needed on a GPU);
# TREX_DLL=<file in /work> replaces the server DLL (e.g. d3d9_trex_rayquery_optional.dll);
# RTX_EXTRA names the rtx.conf additions (default /work/rtx_gpu.conf.extra).
ARCH=win64; SECS=${1:-300}; REMIX=1; KEYS=${2:-}
export WINEPREFIX=/tmp/wp WINEARCH=$ARCH WINEDEBUG=${WINEDEBUG:--all}
export VK_ICD_FILENAMES=${ICD_JSON:-/usr/share/vulkan/icd.d/nvidia_icd.json}
# RAYQUERY_SPOOF=1 (default 0: a GPU with real ray query, e.g. the L4): the layer in /work/vklayer advertises VK_KHR_ray_query
# on a driver that compiles ray query shaders but does not expose the extension
# (NVIDIA B200, driver 580); Remix refuses the GPU without it.
if [ "${RAYQUERY_SPOOF:-0}" = 1 ]; then export VK_LAYER_PATH=/work/vklayer VK_INSTANCE_LAYERS=VK_LAYER_GTA2_rayquery_spoof VK_LOADER_LAYERS_ENABLE=VK_LAYER_GTA2_rayquery_spoof; echo "== ray query spoof layer on"; fi
echo "== vulkan:"; vulkaninfo --summary 2>/dev/null | grep -E "deviceName|driverInfo" | head -2
W=${SCREEN_W:-1280}; H=${SCREEN_H:-720}
if [ "${HOST_DISPLAY:-0}" = 1 ]; then export DISPLAY=${DISPLAY:-:0}; else export DISPLAY=:99; __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json Xvfb :99 -screen 0 ${W}x${H}x24 +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 & fi   # Xvfb GLX on Mesa: the injected NVIDIA EGL vendor segfaults it
sleep 2
# COMPOSITOR=1 (default when xcompmgr exists): a compositing manager on the Xvfb
# screen. The Remix runtime's "new GUI input" overlay is a layered window with
# alpha 0 - invisible on Windows, but without compositing Wine can only map it
# opaque, and it is raised over the picture on every key event (black frames
# while a key is held). With a compositor _NET_WM_WINDOW_OPACITY makes it clear.
if [ "${COMPOSITOR:-1}" = 1 ] && command -v xcompmgr >/dev/null; then xcompmgr -n >/tmp/xcompmgr.log 2>&1 & echo "== compositor: xcompmgr"; sleep 1; fi
# Audio: the container has no sound card, so Wine's DirectSound finds no endpoint
# and the game's Miles Sound System (mss32.dll) opens no digital driver; the game
# then keeps using the dead driver handle and sometimes page-faults in
# AIL_allocate_sample_handle (mss32+0x12353) seconds into a level. A PulseAudio
# null sink gives DirectSound a real, clocked (silent) endpoint, so Miles opens
# normally. (An ALSA "null" pcm is not enough: it has no clock, and the intro movie
# freezes on it.) GTA2_AUDIO=none skips this.
if [ "${GTA2_AUDIO:-pulse}" = pulse ] && command -v pulseaudio >/dev/null 2>&1; then
  export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/tmp/xdg-runtime}; mkdir -p "$XDG_RUNTIME_DIR"
  pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit \
    --load="module-null-sink sink_name=null sink_properties=device.description=null" >/tmp/pulse.log 2>&1 || true
fi
if [ "$ARCH" = win32 ] && [ -d /opt/wp ] && [ ! -d /tmp/wp/drive_c/windows ]; then cp -a /opt/wp/. /tmp/wp/ && echo "== prefix from /opt/wp"; elif [ "$ARCH" = win64 ]; then (unset DISPLAY; wineboot -i >/dev/null 2>&1); else wineboot -i >/dev/null 2>&1; fi   # a *-fast image carries a ready prefix (Dockerfile.fast)
G=/tmp/wp/drive_c/Games/GTA2; mkdir -p "$G"
if mountpoint -q "$G/data" 2>/dev/null; then (cd /game && for f in *; do [ "$f" = data ] || cp -r "$f" "$G"/; done); else cp -r /game/. "$G"/; fi; mkdir -p "$G/player"   # data/ may be a read-only bind mount (game_mounts.sh)
(cd /release && for f in * .[!.]*; do [ -e "$f" ] || continue; mountpoint -q "$G/$f" 2>/dev/null && continue; cp -r "$f" "$G"/; done)   # upstream v1.1: HD cars, voices, Remix mods, ini files (mounted folders are skipped)
cp /stage/*.dll /stage/gta2dx9.ini "$G"/; mountpoint -q "$G/gta2dx9_models" 2>/dev/null || { rm -rf "$G/gta2dx9_models"; cp -r /stage/gta2dx9_models "$G"/; }   # this build: DLLs, ini, models
rm -rf "$G/gta2dx9_textures_hd"; [ "${NO_HD:-0}" = 0 ] && [ -d /stage/gta2dx9_textures_hd ] && cp -r /stage/gta2dx9_textures_hd "$G"/   # HD tiles (DDS/TGA), when generated; NO_HD=1 leaves them out
[ "${NO_MODELS:-0}" = 1 ] && rm -rf "$G/gta2dx9_models"
[ "${NO_CARHD:-0}" = 1 ] && rm -rf "$G/gta2dx9_hd"   # NO_CARHD=1: the upstream HD car maps (402 MB) stay out of the 32-bit process   # NO_MODELS=1: no 3D cars/people/props (32-bit address space under the bridge)
[ "${LAA:-1}" = 1 ] && sh /work/laa.sh "$G/gta2.exe"   # 4 GB address space for the copy in the prefix (HD tiles)
[ -f "${INI_EXTRA:-/work/gta2dx9.ini.extra}" ] && cat "${INI_EXTRA:-/work/gta2dx9.ini.extra}" >> "$G/gta2dx9.ini"   # INI_EXTRA: a run's own [camera]/[renderer] additions
# SWAP_LEVEL=ste makes "level 1" load another district (its map, style and script
# are copied over Downtown's in the prefix copy only); DUMP_TILES=1 turns on the
# renderer's tile dump for the run. Both are for building the HD tile sets.
if [ -n "$SWAP_LEVEL" ]; then for e in gmp sty; do cp "$G/data/$SWAP_LEVEL.$e" "$G/data/wil.$e"; done; cp "$G/data/$SWAP_LEVEL."[sS][cC][rR] "$G/data/wil.SCR"; [ -d "$G/data/$SWAP_LEVEL" ] && rm -rf "$G/data/wil" && cp -r "$G/data/$SWAP_LEVEL" "$G/data/wil"; echo "level 1 is now $SWAP_LEVEL"; fi
[ "${GTA2_INTRO:-1}" = 0 ] && sed -i "s/^intro=1/intro=0/" "$G/gta2dx9.ini"   # GTA2_INTRO=0: skip the intro movie (saves ~25 s per run)
[ -n "$INI_SED" ] && sed -i "$INI_SED" "$G/gta2dx9.ini"   # INI_SED: a sed script over the ini, for turning a documented key off in one run
[ "${DUMP_TILES:-0}" = 1 ] && sed -i 's/^dump_tiles=0/dump_tiles=1/' "$G/gta2dx9.ini"
[ -f "${SETTINGS_EXTRA:-/nonexistent}" ] && cat "$SETTINGS_EXTRA" >> "$G/gta2dx9_settings.ini"; [ -n "${SETTINGS_SED:-}" ] && sed -i "$SETTINGS_SED" "$G/gta2dx9_settings.ini" && grep -n "StartHour\|Paused" "$G/gta2dx9_settings.ini" | head -3   # e.g. a [camera] section for a benchmark
if [ "$REMIX" = 1 ]; then [ -d /work/remix_user_settings ] && mkdir -p /tmp/wp/drive_c/users/root/AppData/Local/NVIDIA/RTXRemix && cp -r /work/remix_user_settings /tmp/wp/drive_c/users/root/AppData/Local/NVIDIA/RTXRemix/user_settings && echo "== remix user settings seeded"; cp -r /remix/. "$G"/; [ -d /work/remix_cache ] && cp -rn /work/remix_cache/. "$G"/ 2>/dev/null && echo "== remix cache restored: $(find /work/remix_cache -type f | wc -l) files"; cp /release/.trex/bridge.conf "$G/.trex/" 2>/dev/null; [ -f /work/bridge.conf.extra ] && cat /work/bridge.conf.extra >> "$G/.trex/bridge.conf"; [ -f "${RTX_EXTRA:-/work/rtx_gpu.conf.extra}" ] && cat "${RTX_EXTRA:-/work/rtx_gpu.conf.extra}" >> "$G/rtx.conf"; [ "${TREX_PATCHED:-0}" = 1 ] && [ -f /work/d3d9_trex_patched.dll ] && cp /work/d3d9_trex_patched.dll "$G/.trex/d3d9.dll"; [ -n "${TREX_DLL:-}" ] && cp "/work/$TREX_DLL" "$G/.trex/d3d9.dll" && echo "server dll: $TREX_DLL"; fi
MODS_HD_SRC=${MODS_HD_SRC:-/package/rtx-remix/mods/gta2hd}   # MODS_HD_SRC: another layer folder to install as gta2hd (e.g. /work/remix_probe/gta2hd, /package/rtx-remix/mods/gta2hd_new)
[ "${MODS_HD:-0}" = 1 ] && [ -d "$MODS_HD_SRC" ] && mkdir -p "$G/rtx-remix/mods/gta2hd" && cp -r "$MODS_HD_SRC"/. "$G/rtx-remix/mods/gta2hd/" && echo "== gta2hd material mod installed from $MODS_HD_SRC ($(ls "$G/rtx-remix/mods/gta2hd/textures" | wc -l) textures, $(grep -c "over \"mat_" "$G/rtx-remix/mods/gta2hd/mod.usda") materials)"   # MODS_HD=1 with -v repo/package:/package:ro
if [ "$REMIX" = 0 ]; then rm -f "$G/d3d9.dll"; fi
wine regedit /S "C:\\Games\\GTA2\\..\\..\\..\\work\\install.reg" >/dev/null 2>&1 || true
cp /work/install.reg "$G/linux_install.reg"; wine regedit /S "C:\\Games\\GTA2\\linux_install.reg" >/dev/null 2>&1
echo "== registry:"; wine reg query 'HKLM\SOFTWARE\DMA Design Ltd\GTA2\Screen' 2>/dev/null | grep -i "rendername\|videoname"
mkdir -p /out; rm -f /out/shot_*.png
cd "$G"
export WINEDLLOVERRIDES="d3d9=n,b;d3ddll,dmavideo,dmaglide,gta2dx9,gta2dx9_vid=n"
ffmpeg -y -loglevel error -f x11grab -framerate 15 -video_size ${W}x${H} -i :99 -t "$SECS" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p /out/game.mp4 &
REC=$!
( wine gta2.exe > /out/game.stdout 2>&1; echo "gta2.exe exited $?" >> /out/game.stdout ) &
if [ -n "$KEYS" ]; then ( bash "$KEYS" > /out/keys.log 2>&1 ) & fi
for i in $(seq 1 $((SECS / 5))); do
  sleep 5
  ffmpeg -y -loglevel error -f x11grab -video_size ${W}x${H} -i :99 -frames:v 1 /out/shot_$(printf %03d $((i*5))).png
  [ $((i % 6)) = 0 ] && { echo "t=$((i*5))s"; xwininfo -root -tree | grep -v "has no name\|Default IME" | grep "(" | head -6; }
done
wait $REC 2>/dev/null
cp "$G/gta2dx9.log" /out/ 2>/dev/null; cp -r "$G/rtx-remix/logs" /out/remix-logs 2>/dev/null; cp -r "$G/Screenshots" /out/remix-screenshots 2>/dev/null; [ -d "$G/rtx-remix/captures" ] && mkdir -p /out/remix-captures && (cd "$G/rtx-remix/captures" && find . -name "*.usd*" -o -name "*.txt" | head -50 | xargs -r -I{} cp --parents {} /out/remix-captures/) 2>/dev/null; [ -d "$G/rtx-remix/captures" ] && find "$G/rtx-remix/captures" -type f | sed "s#$G/##" > /out/remix-captures-files.txt; cp "$G/.trex/"*.log /out/ 2>/dev/null; cp "$G"/*.log /out/ 2>/dev/null; cp "$G/rtx.conf" /out/rtx.conf.used 2>/dev/null; (cd "$G" && ls -la *.dxvk-cache *.remix-pipeline-cache* .trex/*.dxvk-cache .trex/*cache* 2>/dev/null > /out/remix-cache-files.txt); [ -d /work/remix_cache ] && cp "$G"/*.dxvk-cache "$G"/*.remix-pipeline-cache* /work/remix_cache/ 2>/dev/null; [ -d /work/remix_cache ] && cp "$G"/.trex/*cache* /work/remix_cache/ 2>/dev/null; [ -d /work/remix_cache ] && for d in $(cat /out/remix-cache-files.txt 2>/dev/null); do [ -d "$G/$d" ] && cp -r "$G/$d" /work/remix_cache/ 2>/dev/null; [ -f "$G/$d" ] && mkdir -p "/work/remix_cache/$(dirname "$d")" && cp "$G/$d" "/work/remix_cache/$d" 2>/dev/null; done; cp -r /tmp/wp/drive_c/users/root/AppData/Local/NVIDIA/RTXRemix/user_settings /out/remix-user-settings 2>/dev/null; [ -d /work/remix_user_settings ] && true; dmesg 2>/dev/null | grep -i "segfault\|NvRemix" | tail -5 > /out/dmesg.txt
cp -r "$G/gta2dx9_tiles" /out/ 2>/dev/null
wine reg query "HKCU\\Software\\DMA Design Ltd" /s > /out/registry.txt 2>/dev/null; wine reg query "HKLM\\Software\\DMA Design Ltd" /s >> /out/registry.txt 2>/dev/null
tail -5 /out/game.stdout
wineserver -k
