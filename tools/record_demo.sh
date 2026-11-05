#!/usr/bin/env bash
# Linux twin of record_demo.ps1: records the game starting in the classic view
# and switching to first (or third) person by itself a few seconds into a level.
#
#   tools/record_demo.sh [--prefix ~/.local/share/gta2] [--seconds 75] [--switch-after 12]
#                        [--switch-to 2] [--output gta2_view_switch.mp4] [--fps 60]
#
# Needs ffmpeg. On X11 it records the screen with x11grab; on Wayland use
# wf-recorder or OBS instead (ffmpeg cannot grab a Wayland screen directly) -
# the ini part below still does the switching for you.
set -euo pipefail
PREFIX="${WINEPREFIX:-$HOME/.local/share/gta2}"
SECONDS_=75; AFTER=12; TO=2; OUT="gta2_view_switch.mp4"; FPS=60
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --seconds) SECONDS_="$2"; shift 2 ;;
        --switch-after) AFTER="$2"; shift 2 ;;
        --switch-to) TO="$2"; shift 2 ;;
        --output) OUT="$2"; shift 2 ;;
        --fps) FPS="$2"; shift 2 ;;
        *) echo "unknown option $1" >&2; exit 1 ;;
    esac
done
DEST="$PREFIX/drive_c/Games/GTA2"
INI="$DEST/gta2dx9.ini"
[ -f "$INI" ] || { echo "no $INI - run linux/install.sh first" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg is not installed" >&2; exit 1; }

cp "$INI" "$INI.record_demo.bak"
restore() { mv -f "$INI.record_demo.bak" "$INI"; echo "gta2dx9.ini put back."; }
trap restore EXIT
python3 - "$INI" "$AFTER" "$TO" <<'PY'
import re, sys
path, after, to = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path, encoding="utf-8", errors="replace").read()
def setkey(s, key, value):
    pat = re.compile(r"(?m)^\s*%s\s*=.*$" % re.escape(key))
    if pat.search(s): return pat.sub("%s=%s" % (key, value), s, count=1)
    if re.search(r"(?m)^\[camera\]\s*$", s): return re.sub(r"(?m)^\[camera\]\s*$", "[camera]\n%s=%s" % (key, value), s, count=1)
    return s + "\n[camera]\n%s=%s\n" % (key, value)
s = setkey(s, "mode", "classic"); s = setkey(s, "demo_switch_seconds", after); s = setkey(s, "demo_switch_to", to)
open(path, "w", encoding="utf-8").write(s)
PY

if [ -n "${DISPLAY:-}" ]; then
    SIZE="$(xdpyinfo 2>/dev/null | awk '/dimensions/{print $2}')"
    echo "Recording $DISPLAY (${SIZE:-?}) for $SECONDS_ s to $OUT ..."
    ffmpeg -y -loglevel error -f x11grab -framerate "$FPS" ${SIZE:+-video_size "$SIZE"} -i "$DISPLAY" \
        -t "$SECONDS_" -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p "$OUT" &
    REC=$!
else
    echo "No X11 DISPLAY: start wf-recorder or OBS yourself now; the view will switch $AFTER s into the level."
    REC=""
fi
sleep 2
echo "Starting GTA2. Start a level as usual; $AFTER s after it comes up the view switches by itself."
"$(dirname "$0")/../linux/run.sh" --prefix "$PREFIX" &
GAME=$!
if [ -n "$REC" ]; then wait "$REC"; echo "Done: $OUT"; else sleep "$SECONDS_"; fi
kill "$GAME" 2>/dev/null || true
