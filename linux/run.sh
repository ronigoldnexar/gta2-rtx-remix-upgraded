#!/usr/bin/env bash
# Starts GTA2 with the mod in the Wine prefix linux/install.sh made.
#
#   linux/run.sh [--prefix ~/.local/share/gta2] [--log]
#
# --log tails gta2dx9.log while the game runs, which is where the renderer
# says what it found (the player for the camera views, Remix or not, and so on).
set -euo pipefail
PREFIX="${WINEPREFIX:-$HOME/.local/share/gta2}"
TAIL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --log) TAIL=1; shift ;;
        *) echo "unknown option $1" >&2; exit 1 ;;
    esac
done
export WINEPREFIX="$PREFIX"
export WINEDEBUG="${WINEDEBUG:--all}"
DEST="$WINEPREFIX/drive_c/Games/GTA2"
[ -f "$DEST/gta2.exe" ] || { echo "no game in $DEST - run linux/install.sh first" >&2; exit 1; }
# The renderer presents into a topmost window of its own over the game's; a
# virtual desktop keeps both inside one window of the host's desktop, which is
# what Wine's window manager integration handles best.
: "${GTA2_DESKTOP:=1920x1080}"
cd "$DEST"
if [ "$TAIL" = 1 ]; then
    : > gta2dx9.log
    tail -f gta2dx9.log &
    TAILPID=$!
    trap 'kill $TAILPID 2>/dev/null || true' EXIT
fi
if [ -n "$GTA2_DESKTOP" ]; then
    exec wine explorer /desktop=GTA2,"$GTA2_DESKTOP" gta2.exe
else
    exec wine gta2.exe
fi
