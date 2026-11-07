#!/usr/bin/env bash
# Inside the container. Sets up the prefix, installs game + mod, starts the
# game on Xvfb, records, screenshots every few seconds, collects logs.
#   run_game_gpu.sh (GPU rendering through VirtualGL; image gta2-gpugl, docker --gpus) <arch win32|win64> <seconds> <remix 0|1> [keys script]
ARCH=${1:-win32}; SECS=${2:-90}; REMIX=${3:-0}; KEYS=${4:-}
export WINEPREFIX=/tmp/wp WINEARCH=$ARCH WINEDEBUG=${WINEDEBUG:--all}
# GPU run: no llvmpipe override; wined3d's OpenGL goes through VirtualGL to the NVIDIA EGL device.
export VGL_DISPLAY=${VGL_DISPLAY:-egl0} VGL_VERBOSE=${VGL_VERBOSE:-1}
export VK_ICD_FILENAMES=${ICD_JSON:-$(ls /usr/share/vulkan/icd.d/lvp_icd*.json 2>/dev/null | tr "\n" ":")}
W=${SCREEN_W:-1280}; H=${SCREEN_H:-720}
if [ "${HOST_DISPLAY:-0}" = 1 ]; then export DISPLAY=${DISPLAY:-:0}; else export DISPLAY=:99; __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json Xvfb :99 -screen 0 ${W}x${H}x24 +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 & fi   # Xvfb's own GLX must stay on Mesa: with the NVIDIA EGL vendor (and the runtime's libnvidia-egl-gbm) it segfaults; vglrun below still goes to the GPU
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
sleep 2; if [ "$ARCH" = win32 ] && [ -d /opt/wp ] && [ ! -d /tmp/wp/drive_c/windows ]; then cp -a /opt/wp/. /tmp/wp/ && echo "== prefix from /opt/wp"; elif [ "$ARCH" = win64 ]; then (unset DISPLAY; wineboot -i >/dev/null 2>&1); else wineboot -i >/dev/null 2>&1; fi   # a *-fast image carries a ready prefix (Dockerfile.fast)
G=/tmp/wp/drive_c/Games/GTA2; mkdir -p "$G"
if mountpoint -q "$G/data" 2>/dev/null; then (cd /game && for f in *; do [ "$f" = data ] || cp -r "$f" "$G"/; done); else cp -r /game/. "$G"/; fi; mkdir -p "$G/player"   # data/ may be a read-only bind mount (game_mounts.sh)
(cd /release && for f in * .[!.]*; do [ -e "$f" ] || continue; mountpoint -q "$G/$f" 2>/dev/null && continue; cp -r "$f" "$G"/; done)   # upstream v1.1: HD cars, voices, Remix mods, ini files (mounted folders are skipped)
cp /stage/*.dll /stage/gta2dx9.ini "$G"/; mountpoint -q "$G/gta2dx9_models" 2>/dev/null || { rm -rf "$G/gta2dx9_models"; cp -r /stage/gta2dx9_models "$G"/; }   # this build: DLLs, ini, models
mountpoint -q "$G/gta2dx9_textures_hd" 2>/dev/null || { rm -rf "$G/gta2dx9_textures_hd"; [ -d /stage/gta2dx9_textures_hd ] && cp -r /stage/gta2dx9_textures_hd "$G"/; }   # HD tiles (DDS/TGA), when generated
[ "${LAA:-1}" = 1 ] && sh /work/laa.sh "$G/gta2.exe"   # 4 GB address space for the copy in the prefix (HD tiles)
[ -f "${INI_EXTRA:-/work/gta2dx9.ini.extra}" ] && cat "${INI_EXTRA:-/work/gta2dx9.ini.extra}" >> "$G/gta2dx9.ini"   # INI_EXTRA: a run's own [camera]/[renderer] additions
# SWAP_LEVEL=ste makes "level 1" load another district (its map, style and script
# are copied over Downtown's in the prefix copy only); DUMP_TILES=1 turns on the
# renderer's tile dump for the run. Both are for building the HD tile sets.
if [ -n "$SWAP_LEVEL" ] && [ "$SWAP_LEVEL" != wil ]; then for e in gmp sty; do cp "$G/data/$SWAP_LEVEL.$e" "$G/data/wil.$e"; done; cp "$G/data/$SWAP_LEVEL."[sS][cC][rR] "$G/data/wil.SCR"; [ -d "$G/data/$SWAP_LEVEL" ] && rm -rf "$G/data/wil" && cp -r "$G/data/$SWAP_LEVEL" "$G/data/wil"; echo "level 1 is now $SWAP_LEVEL"; fi
[ "${GTA2_INTRO:-1}" = 0 ] && sed -i "s/^intro=1/intro=0/" "$G/gta2dx9.ini"   # GTA2_INTRO=0: skip the intro movie (saves ~25 s per run)
[ -n "$INI_SED" ] && sed -i "$INI_SED" "$G/gta2dx9.ini"   # INI_SED: a sed script over the ini, for turning a documented key off in one run
[ "${DUMP_TILES:-0}" = 1 ] && sed -i 's/^dump_tiles=0/dump_tiles=1/' "$G/gta2dx9.ini"
[ -f "${SETTINGS_EXTRA:-/nonexistent}" ] && cat "$SETTINGS_EXTRA" >> "$G/gta2dx9_settings.ini"   # e.g. a [camera] section for a benchmark
if [ "$REMIX" = 1 ]; then cp -r /remix/. "$G"/; cp /release/.trex/bridge.conf "$G/.trex/" 2>/dev/null; [ -f /work/bridge.conf.extra ] && cat /work/bridge.conf.extra >> "$G/.trex/bridge.conf"; [ -f /work/rtx.conf.extra ] && cat /work/rtx.conf.extra >> "$G/rtx.conf"; [ -f /work/d3d9_trex_patched.dll ] && cp /work/d3d9_trex_patched.dll "$G/.trex/d3d9.dll"; fi
if [ "$REMIX" = 0 ]; then rm -f "$G/d3d9.dll"; fi
wine regedit /S "C:\\Games\\GTA2\\..\\..\\..\\work\\install.reg" >/dev/null 2>&1 || true
cp /work/install.reg "$G/linux_install.reg"; wine regedit /S "C:\\Games\\GTA2\\linux_install.reg" >/dev/null 2>&1
echo "== registry:"; wine reg query 'HKLM\SOFTWARE\DMA Design Ltd\GTA2\Screen' 2>/dev/null | grep -i "rendername\|videoname"
mkdir -p /out; rm -f /out/shot_*.png
cd "$G"
export WINEDLLOVERRIDES="d3d9=n,b;d3ddll,dmavideo,dmaglide,gta2dx9,gta2dx9_vid=n"
ffmpeg -y -loglevel error -f x11grab -framerate ${FPS:-15} -video_size ${W}x${H} -i :99 -t "$SECS" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p /out/game.mp4 &
REC=$!
( vglrun -d "$VGL_DISPLAY" wine gta2.exe > /out/game.stdout 2>&1; echo "gta2.exe exited $?" >> /out/game.stdout ) &
if [ -n "$KEYS" ]; then ( bash "$KEYS" > /out/keys.log 2>&1 ) & fi
for i in $(seq 1 $((SECS / 5))); do
  sleep 5
  ffmpeg -y -loglevel error -f x11grab -video_size ${W}x${H} -i :99 -frames:v 1 /out/shot_$(printf %03d $((i*5))).png
  [ $((i % 6)) = 0 ] && { echo "t=$((i*5))s"; xwininfo -root -tree | grep -v "has no name\|Default IME" | grep "(" | head -6; }
done
wait $REC 2>/dev/null
cp "$G/gta2dx9.log" /out/ 2>/dev/null; cp -r "$G/rtx-remix/logs" /out/remix-logs 2>/dev/null
cp -r "$G/gta2dx9_tiles" /out/ 2>/dev/null
wine reg query "HKCU\\Software\\DMA Design Ltd" /s > /out/registry.txt 2>/dev/null; wine reg query "HKLM\\Software\\DMA Design Ltd" /s >> /out/registry.txt 2>/dev/null
tail -5 /out/game.stdout
wineserver -k
