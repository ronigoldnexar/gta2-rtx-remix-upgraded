#!/usr/bin/env bash
# Inside the container: the game for a person, not a keys script. Same prefix
# setup as run_game_gpu.sh / run_game_remix_gpu.sh, then the display is served to
# a browser: Xvfb -> x11vnc -> websockify/noVNC on $PLAY_PORT (6080), and the game's
# sound (PulseAudio null sink -> play_audio.py -> Opus over a websocket on the same port). Runs until
# the container is stopped.   play_game.sh <plain|remix>
MODE=${1:-plain}
export PLAY_PORT=${PLAY_PORT:-6080}
W=${SCREEN_W:-1280}; H=${SCREEN_H:-720}
if [ "$MODE" = remix ]; then ARCH=win64; REMIX=1; else ARCH=win32; REMIX=0; fi
export WINEPREFIX=/tmp/wp WINEARCH=$ARCH WINEDEBUG=${WINEDEBUG:--all}
export VGL_DISPLAY=${VGL_DISPLAY:-egl0} VGL_VERBOSE=0
if [ "$REMIX" = 1 ]; then export VK_ICD_FILENAMES=${ICD_JSON:-/usr/share/vulkan/icd.d/nvidia_icd.json}
else export VK_ICD_FILENAMES=${ICD_JSON:-$(ls /usr/share/vulkan/icd.d/lvp_icd*.json 2>/dev/null | tr "\n" ":")}; fi

export DISPLAY=:99
# Xvfb's own GLX stays on Mesa (the injected NVIDIA EGL vendor segfaults it); the game goes to the GPU through vglrun (plain) or the Remix server's Vulkan (remix).
__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json Xvfb :99 -screen 0 ${W}x${H}x24 +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
sleep 2
if [ "$REMIX" = 1 ] && command -v xcompmgr >/dev/null; then xcompmgr -n >/tmp/xcompmgr.log 2>&1 & sleep 1; fi   # Remix's layered input overlay needs compositing (black frames otherwise)
# A clocked null audio sink: without one the game's Miles Sound System faults now and then (see run_game_gpu.sh).
if command -v pulseaudio >/dev/null 2>&1; then
  export XDG_RUNTIME_DIR=/tmp/xdg-runtime; mkdir -p "$XDG_RUNTIME_DIR"
  pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit --load="module-null-sink sink_name=null sink_properties=device.description=null" >/tmp/pulse.log 2>&1 || true
fi
# Game audio for the page: the null sink's monitor, Opus-encoded, on the page's own port (websocket path /audio,
# see play_audio.py). From the work folder like the landing page, else the copy baked into the image. PLAY_AUDIO=0 turns it off.
AUDIO_PY=/work/play_audio.py; [ -f "$AUDIO_PY" ] || AUDIO_PY=/opt/play/play_audio.py
AUDIO=false
if [ "${PLAY_AUDIO:-1}" = 1 ] && [ -f "$AUDIO_PY" ] && command -v parec >/dev/null 2>&1 && pactl info >/dev/null 2>&1; then
  python3 "$AUDIO_PY" serve >/tmp/play_audio.log 2>&1 &
  AUDIO=true
fi

# The VNC server and the web side, up before the game so the page is reachable while Wine boots.
PW=(); [ -n "${PLAY_PASSWORD:-}" ] && { x11vnc -storepasswd "$PLAY_PASSWORD" /tmp/vncpass >/dev/null 2>&1; PW=(-rfbauth /tmp/vncpass); } || PW=(-nopw)
# PLAY_X11VNC: the encoder's tuning flags (PERF-3 measured them with a browser connected, docs/performance.md);
# PLAY_VNC_NICE: its CPU niceness (the game keeps priority over the encoder on the container's CPUs).
X11VNC_TUNE=${PLAY_X11VNC:--noxdamage -defer 15 -wait 15 -threads}
nice -n "${PLAY_VNC_NICE:-0}" x11vnc -display :99 -shared -forever $X11VNC_TUNE -nocursorshape -cursor arrow -xkb "${PW[@]}" -rfbport 5900 -quiet -bg -o /tmp/x11vnc.log
printf '{"mode":"%s","devtools":%s,"password":"%s","audio":%s}\n' "$MODE" "$([ "${PLAY_DEVTOOLS:-0}" = 1 ] && echo true || echo false)" "${PLAY_PASSWORD:-}" "$AUDIO" > /usr/share/novnc/play_mode.json
[ -f /work/play_index.html ] && cp /work/play_index.html /usr/share/novnc/index.html   # the landing page from the work folder, so edits need no image rebuild
# websockify with a path router (play_audio.py web): /audio and /audio-pcm go to the audio server, everything else to VNC.
if [ "$AUDIO" = true ]; then python3 "$AUDIO_PY" web "$PLAY_PORT" >/tmp/websockify.log 2>&1 &
else websockify --web /usr/share/novnc "$PLAY_PORT" localhost:5900 >/tmp/websockify.log 2>&1 & fi
echo "== browser: http://localhost:$PLAY_PORT/  (vnc on :5900 inside the container)"

if [ "$ARCH" = win64 ]; then (unset DISPLAY; wineboot -i >/dev/null 2>&1; wineserver -w); else wineboot -i >/dev/null 2>&1; fi   # wineserver -w: the game must not start inside the headless boot's driverless desktop (no window)
G=/tmp/wp/drive_c/Games/GTA2; mkdir -p "$G"
cp -r /game/. "$G"/; mkdir -p "$G/player"
cp -r /release/. "$G"/
cp /stage/*.dll /stage/gta2dx9.ini $(ls /stage/gta2dx9_effects.ini 2>/dev/null) "$G"/; rm -rf "$G/gta2dx9_models"; cp -r /stage/gta2dx9_models "$G"/
[ -f /work/stage_copy_check.sh ] && { bash /work/stage_copy_check.sh "$G" || exit 3; }   # the stage build, not /release v1.1, is what runs (a stage rewritten mid-copy left v1.1 in place)
rm -rf "$G/gta2dx9_textures_hd"; [ -d /stage/gta2dx9_textures_hd ] && cp -r /stage/gta2dx9_textures_hd "$G"/
[ "${LAA:-1}" = 1 ] && sh /work/laa.sh "$G/gta2.exe"
if [ "${PLAY_DEVTOOLS:-0}" = 1 ]; then sed -i 's/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F11/' "$G/gta2dx9.ini"; fi
# Mouse look is off for a browser session unless asked for: a VNC client's pointer is absolute, so the warp-to-centre look scheme jumps.
sed -i "s/^mouse_look=.*/mouse_look=${PLAY_MOUSE:-0}/" "$G/gta2dx9.ini"
[ -n "${INI_SED:-}" ] && sed -i "$INI_SED" "$G/gta2dx9.ini"
[ -n "${SETTINGS_SED:-}" ] && [ -f "$G/gta2dx9_settings.ini" ] && sed -i "$SETTINGS_SED" "$G/gta2dx9_settings.ini"
if [ "$REMIX" = 1 ]; then
  [ -d /work/remix_user_settings ] && mkdir -p /tmp/wp/drive_c/users/root/AppData/Local/NVIDIA/RTXRemix && cp -r /work/remix_user_settings /tmp/wp/drive_c/users/root/AppData/Local/NVIDIA/RTXRemix/user_settings
  cp -r /remix/. "$G"/; [ -d /work/remix_cache ] && cp -rn /work/remix_cache/. "$G"/ 2>/dev/null
  cp /release/.trex/bridge.conf "$G/.trex/" 2>/dev/null; [ -f /work/bridge.conf.extra ] && cat /work/bridge.conf.extra >> "$G/.trex/bridge.conf"
  [ -f "${RTX_EXTRA:-/work/rtx_gpu.conf.extra}" ] && cat "${RTX_EXTRA:-/work/rtx_gpu.conf.extra}" >> "$G/rtx.conf"
  # The page's look: the play preset (no motion blur, vignette or chromatic aberration; slow exposure; REMIX-VERIFY).
  # PLAY_RTX_PRESET=rtx_showcase.conf.extra for the showcase look.
  [ -f "/work/${PLAY_RTX_PRESET:-rtx_play.conf.extra}" ] && cat "/work/${PLAY_RTX_PRESET:-rtx_play.conf.extra}" >> "$G/rtx.conf"
  MODS_HD_SRC=${MODS_HD_SRC:-/package/rtx-remix/mods/gta2hd}
  [ "${MODS_HD:-1}" = 1 ] && [ -d "$MODS_HD_SRC" ] && mkdir -p "$G/rtx-remix/mods/gta2hd" && cp -r "$MODS_HD_SRC"/. "$G/rtx-remix/mods/gta2hd/"
else
  rm -f "$G/d3d9.dll"
fi
cp /work/install.reg "$G/linux_install.reg"; wine regedit /S "C:\\Games\\GTA2\\linux_install.reg" >/dev/null 2>&1
cd "$G"
export WINEDLLOVERRIDES="d3d9=n,b;d3ddll,dmavideo,dmaglide,gta2dx9,gta2dx9_vid=n"
echo "== starting the game ($MODE)"
if [ "$REMIX" = 1 ]; then ( wine gta2.exe > /tmp/game.stdout 2>&1; echo "gta2.exe exited $?" >> /tmp/game.stdout ) &
else ( vglrun -d "$VGL_DISPLAY" wine gta2.exe > /tmp/game.stdout 2>&1; echo "gta2.exe exited $?" >> /tmp/game.stdout ) & fi
# Keyboard focus to the game window once it exists; after that the browser's clicks keep it.
for i in $(seq 1 90); do sleep 2; WIN=$(xwininfo -root -tree 2>/dev/null | grep '"GTA2"' | grep "648x514\|640x480\|1280x720\|1024x768" | head -1 | awk '{print $1}'); [ -n "$WIN" ] && break; done
[ -n "$WIN" ] && { xdotool windowactivate "$WIN" 2>/dev/null; xdotool windowfocus --sync "$WIN" 2>/dev/null; echo "== game window $WIN focused"; }
# Keep serving until the container is stopped; the log is mirrored to /out for the host.
while true; do sleep 15; [ -d /out ] && cp "$G/gta2dx9.log" /out/ 2>/dev/null; if ! pgrep -f gta2.exe >/dev/null; then echo "== game exited, restarting"; cd "$G"; if [ "$REMIX" = 1 ]; then ( wine gta2.exe >> /tmp/game.stdout 2>&1 ) & else ( vglrun -d "$VGL_DISPLAY" wine gta2.exe >> /tmp/game.stdout 2>&1 ) & fi; for i in $(seq 1 45); do sleep 2; WIN=$(xwininfo -root -tree 2>/dev/null | grep '"GTA2"' | grep "648x514\|640x480\|1280x720\|1024x768" | head -1 | awk '{print $1}'); [ -n "$WIN" ] && break; done; [ -n "$WIN" ] && { xdotool windowfocus --sync "$WIN" 2>/dev/null; echo "== game window $WIN focused again"; }; fi; done
