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
cp /stage/*.dll /stage/gta2dx9.ini $(ls /stage/gta2dx9_effects.ini 2>/dev/null) "$G"/; mountpoint -q "$G/gta2dx9_models" 2>/dev/null || { rm -rf "$G/gta2dx9_models"; cp -r /stage/gta2dx9_models "$G"/; }   # this build: DLLs, ini, models
mountpoint -q "$G/gta2dx9_textures_hd" 2>/dev/null || { rm -rf "$G/gta2dx9_textures_hd"; [ -d /stage/gta2dx9_textures_hd ] && cp -r /stage/gta2dx9_textures_hd "$G"/; }   # HD tiles (DDS/TGA), when generated
[ "${LAA:-1}" = 1 ] && sh /work/laa.sh "$G/gta2.exe"   # 4 GB address space for the copy in the prefix (HD tiles)
[ -f "${INI_EXTRA:-/work/gta2dx9.ini.extra}" ] && cat "${INI_EXTRA:-/work/gta2dx9.ini.extra}" >> "$G/gta2dx9.ini"   # INI_EXTRA: a run's own [camera]/[renderer] additions
# SWAP_LEVEL=ste makes "level 1" load another district (its map, style and script
# are copied over Downtown's in the prefix copy only); DUMP_TILES=1 turns on the
# renderer's tile dump for the run. Both are for building the HD tile sets.
if [ -n "$SWAP_LEVEL" ] && [ "$SWAP_LEVEL" != wil ]; then bash /work/swap_level.sh "$G" "$SWAP_LEVEL" || { echo "run aborted: the level swap did not take"; exit 3; }; fi
[ "${GTA2_INTRO:-1}" = 0 ] && sed -i "s/^intro=1/intro=0/" "$G/gta2dx9.ini"   # GTA2_INTRO=0: skip the intro movie (saves ~25 s per run)
[ -n "$KEYS" ] && sed -i 's/^\(scene_key=\)\(\r\?\)$/\1F10\2/; s/^\(warp_key=\)\(\r\?\)$/\1F9\2/' "$G/gta2dx9.ini"   # a run with a keys script is a devtools run: bind the scene/warp keys when the ini leaves them empty (the DLL reads them once at start; a script's '# ini-sed:' line or INI_SED below still overrides)
[ -n "$INI_SED" ] && sed -i "$INI_SED" "$G/gta2dx9.ini"   # INI_SED: a sed script over the ini, for turning a documented key off in one run
[ -n "$KEYS" ] && [ -f "$KEYS" ] && KSED=$(sed -n 's/^# *ini-sed: *//p' "$KEYS" | paste -sd';') && [ -n "$KSED" ] && sed -i "$KSED" "$G/gta2dx9.ini" && echo "== ini-sed from $(basename "$KEYS"): $KSED"   # a keys script declares the ini it needs (e.g. the devtools scene key, read once at start) in '# ini-sed:' lines
[ "${DUMP_TILES:-0}" = 1 ] && sed -i 's/^dump_tiles=0/dump_tiles=1/' "$G/gta2dx9.ini"
[ -f "${SETTINGS_EXTRA:-/nonexistent}" ] && cat "$SETTINGS_EXTRA" >> "$G/gta2dx9_settings.ini"; [ -n "${SETTINGS_SED:-}" ] && sed -i "$SETTINGS_SED" "$G/gta2dx9_settings.ini"   # SETTINGS_SED: the saved settings file overrides the ini (FpsCap, StartHour...)
if [ "$REMIX" = 1 ]; then cp -r /remix/. "$G"/; cp /release/.trex/bridge.conf "$G/.trex/" 2>/dev/null; [ -f /work/bridge.conf.extra ] && cat /work/bridge.conf.extra >> "$G/.trex/bridge.conf"; [ -f /work/rtx.conf.extra ] && cat /work/rtx.conf.extra >> "$G/rtx.conf"; [ -f /work/d3d9_trex_patched.dll ] && cp /work/d3d9_trex_patched.dll "$G/.trex/d3d9.dll"; fi
if [ "$REMIX" = 0 ]; then rm -f "$G/d3d9.dll"; fi
wine regedit /S "C:\\Games\\GTA2\\..\\..\\..\\work\\install.reg" >/dev/null 2>&1 || true
cp /work/install.reg "$G/linux_install.reg"; wine regedit /S "C:\\Games\\GTA2\\linux_install.reg" >/dev/null 2>&1
echo "== registry:"; wine reg query 'HKLM\SOFTWARE\DMA Design Ltd\GTA2\Screen' 2>/dev/null | grep -i "rendername\|videoname"
mkdir -p /out; rm -f /out/shot_*.png
cd "$G"
export WINEDLLOVERRIDES="d3d9=n,b;d3ddll,dmavideo,dmaglide,gta2dx9,gta2dx9_vid=n"
# REMIX-PIPELINE (9 Nov): the recording ends with the keys script (END_ON_KEYS=1, default; tail KEYS_TAIL=3 s), not at SECS: SECS is a cap.
# The 12:43 demo ran SECS=2400 while its script stopped driving the player long before: 20 minutes of frozen camera. A keys script that
# ends (or touches /out/.keys_done itself) closes the file; MOTION_WATCHDOG=1 also ends it when the picture has not moved for
# MOTION_WINDOW s (60; mean frame difference between shots under MOTION_FLOOR 0.15), for a script that hangs instead of ending.
# The log gets 'recording: ... s' (achieved length, why it ended); END_ON_KEYS=0 restores the old fixed length.
T0=$(date +%s.%N); rm -f /out/.keys_done
if [ "${FPS:-15}" = 0 ]; then sleep "$SECS" & else ffmpeg -y -loglevel error -f x11grab -framerate ${FPS:-15} -video_size ${W}x${H} -i :99 -t "$SECS" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -movflags +frag_keyframe+empty_moov+default_base_moof /out/game_raw.mp4 & fi   # FPS=0: no video, screenshots only
REC=$!
( vglrun -d "$VGL_DISPLAY" wine gta2.exe > /out/game.stdout 2>&1; echo "gta2.exe exited $?" >> /out/game.stdout ) &
if [ -n "$KEYS" ]; then ( bash "$KEYS" > /out/keys.log 2>&1; echo "keys script ended $(date +%s.%N)" > /out/.keys_done ) & fi
EV=${SHOTS_EVERY:-5}; WHY="run length $SECS s reached"; LASTMOVE=$(date +%s); PREV=; LASTN=
while :; do
  sleep 1; NOW=$(date +%s.%N); N=$(python3 -c "print(int($NOW - $T0))")
  [ "$N" -ge "$SECS" ] && break
  # a keys script that has finished its work (or touched /out/.keys_done): end the run after a short tail, closing the recording properly
  if [ -f /out/.keys_done ] && [ "${END_ON_KEYS:-1}" = 1 ]; then sleep "${KEYS_TAIL:-3}"; WHY="keys script ended"; echo "keys script done at t=${N}s: ending the run after a ${KEYS_TAIL:-3} s tail"; break; fi
  if [ $((N % EV)) = 0 ] && [ "$N" != "$LASTN" ]; then LASTN=$N
    CUR=/out/shot_$(printf %03d $N).png
    ffmpeg -y -loglevel error -f x11grab -video_size ${W}x${H} -i :99 -frames:v 1 "$CUR"
    [ $((N % 30)) = 0 ] && { echo "t=${N}s"; xwininfo -root -tree | grep -v "has no name\|Default IME" | grep "(" | head -6; }
    if [ "${MOTION_WATCHDOG:-0}" = 1 ]; then
      if [ -n "$PREV" ] && D=$(ffmpeg -loglevel error -i "$PREV" -i "$CUR" -lavfi "blend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-" -f null - 2>/dev/null | sed -n 's/.*YAVG=//p' | head -1) && [ -n "$D" ]; then
        [ "$(python3 -c "print(int($D > ${MOTION_FLOOR:-0.15}))")" = 1 ] && LASTMOVE=$(date +%s)
        [ $(( $(date +%s) - LASTMOVE )) -ge ${MOTION_WINDOW:-60} ] && { WHY="motion watchdog: picture still for ${MOTION_WINDOW:-60} s"; echo "$WHY: ending the run"; break; }
      fi; PREV=$CUR
    fi
  fi
done
END=$(date +%s.%N)
kill -INT $REC 2>/dev/null
wait $REC 2>/dev/null
[ -f /out/game_raw.mp4 ] && ffmpeg -y -loglevel error -i /out/game_raw.mp4 -c copy -movflags +faststart /out/game.mp4 2>/dev/null && rm -f /out/game_raw.mp4   # faststart remux (the raw file is fragmented so a killed recorder still leaves a playable file)
echo "recording: $(python3 -c "print(round($END - $T0))") s of run; game.mp4 $(ffprobe -v error -show_entries format=duration -of csv=p=0 /out/game.mp4 2>/dev/null) s; ended by: $WHY" | tee -a /out/recording.txt
cp "$G/gta2dx9.log" /out/ 2>/dev/null; cp -r "$G/rtx-remix/logs" /out/remix-logs 2>/dev/null
cp -r "$G/gta2dx9_tiles" /out/ 2>/dev/null
wine reg query "HKCU\\Software\\DMA Design Ltd" /s > /out/registry.txt 2>/dev/null; wine reg query "HKLM\\Software\\DMA Design Ltd" /s >> /out/registry.txt 2>/dev/null
tail -5 /out/game.stdout
wineserver -k
