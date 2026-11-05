#!/usr/bin/env bash
# Inside the container. Sets up the prefix, installs game + mod, starts the
# game on Xvfb, records, screenshots every few seconds, collects logs.
#   run_game.sh <arch win32|win64> <seconds> <remix 0|1> [keys script]
ARCH=${1:-win32}; SECS=${2:-90}; REMIX=${3:-0}; KEYS=${4:-}
export DISPLAY=:99 WINEPREFIX=/tmp/wp WINEARCH=$ARCH WINEDEBUG=${WINEDEBUG:--all}
export MESA_LOADER_DRIVER_OVERRIDE=llvmpipe LP_NUM_THREADS=${LP_NUM_THREADS:-32}
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.x86_64.json:/usr/share/vulkan/icd.d/lvp_icd.i686.json
W=${SCREEN_W:-1280}; H=${SCREEN_H:-720}
Xvfb :99 -screen 0 ${W}x${H}x24 +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
sleep 2; if [ "$ARCH" = win64 ]; then (unset DISPLAY; wineboot -i >/dev/null 2>&1); else wineboot -i >/dev/null 2>&1; fi
G=/tmp/wp/drive_c/Games/GTA2; mkdir -p "$G"
cp -r /game/. "$G"/; mkdir -p "$G/player"
cp -r /release/. "$G"/            # upstream v1.1: HD cars, voices, Remix mods, ini files
cp /stage/*.dll /stage/gta2dx9.ini "$G"/   # this build's DLLs and ini
[ -f /work/gta2dx9.ini.extra ] && cat /work/gta2dx9.ini.extra >> "$G/gta2dx9.ini"
if [ "$REMIX" = 1 ]; then cp -r /remix/. "$G"/; cp /release/.trex/bridge.conf "$G/.trex/" 2>/dev/null; fi
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
cp "$G/gta2dx9.log" /out/ 2>/dev/null; cp -r "$G/rtx-remix/logs" /out/remix-logs 2>/dev/null
wine reg query "HKCU\\Software\\DMA Design Ltd" /s > /out/registry.txt 2>/dev/null; wine reg query "HKLM\\Software\\DMA Design Ltd" /s >> /out/registry.txt 2>/dev/null
tail -5 /out/game.stdout
wineserver -k
