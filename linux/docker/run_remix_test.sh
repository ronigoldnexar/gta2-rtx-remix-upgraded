#!/usr/bin/env bash
# Inside the container: Xvfb, a 64-bit Wine prefix, the D3D9 test app with the
# Remix bridge beside it, a recording of the display, and the logs.
set -u
export DISPLAY=:99 WINEPREFIX=/tmp/wp WINEARCH=win64 WINEDEBUG=${WINEDEBUG:--all}
export WINEDLLOVERRIDES="d3d9=n,b"; export WINEDEBUG=${WINEDEBUG:--all}
export LP_NUM_THREADS=${LP_NUM_THREADS:-32}
export MESA_LOADER_DRIVER_OVERRIDE=llvmpipe
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.x86_64.json:/usr/share/vulkan/icd.d/lvp_icd.i686.json
MODE=${1:-remix}; FRAMES=${2:-60}; SECS=${3:-120}
Xvfb :99 -screen 0 1280x800x24 +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
sleep 2
# The prefix is made with no display: with one, Wine 10 leaves syswow64 empty.
(unset DISPLAY; wineboot -i >/dev/null 2>&1)
cd /work
rm -rf rtx-remix/logs; mkdir -p /out
if [ "$MODE" = "plain" ]; then export WINEDLLOVERRIDES="d3d9=b"; fi
echo "== vulkan devices seen on the host side:"; vulkaninfo --summary 2>/dev/null | grep -E "deviceName|apiVersion" | head -4
ffmpeg -y -loglevel error -f x11grab -framerate 10 -video_size 1280x800 -i :99 -t "$SECS" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p /out/$MODE.mp4 &
REC=$!
sleep 1
( timeout "$SECS" wine d3d9test32.exe "$FRAMES" 640 480 ${PACE:-100} ; echo "app exit $?" ) 2>&1 | grep -v "fixme" > /out/$MODE.app.log &
APP=$!
for i in $(seq 1 ${SHOTS:-6}); do sleep ${SHOT_EVERY:-10}; import -window root /out/$MODE.shot_$(printf %02d $i).png 2>/dev/null; kill -0 $APP 2>/dev/null || break; done
wait $APP; tail -6 /out/$MODE.app.log
sleep 2
ffmpeg -y -loglevel error -f x11grab -video_size 1280x800 -i :99 -frames:v 1 /out/$MODE.final.png
kill $REC 2>/dev/null; wait $REC 2>/dev/null
wineserver -k 2>/dev/null
ls -la rtx-remix/logs 2>/dev/null && for f in rtx-remix/logs/*; do echo "=== $f"; grep -v "^$" "$f" | head -80; done > /out/$MODE.remix.log 2>&1
ls -la /out
