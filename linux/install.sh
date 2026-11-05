#!/usr/bin/env bash
# Installs GTA2 RTX Upgraded into a Wine prefix on Linux.
#
#   linux/install.sh --game /path/to/GTA2            # your GTA2 folder (has gta2.exe)
#                    [--prefix ~/.local/share/gta2]  # the Wine prefix to make or reuse
#                    [--files stage]                 # the mod files: a built stage/ or an
#                                                    #   unzipped release (default: stage/,
#                                                    #   else the newest release zip beside it)
#                    [--release path/to/GTA2_RTX_Upgraded_v1.1.zip]  # HD cars, voices, Remix mods
#                    [--dxvk]                        # fetch DXVK for Direct3D 9 over Vulkan
#
# What it does, in order:
#   1. makes a 32-bit Wine prefix (GTA2 is a 32-bit program) and installs the
#      DirectX 9 runtime pieces the renderer needs - no winetricks required;
#   2. copies the game folder into the prefix's C:\Games\GTA2 (yours is not touched);
#   3. unzips the upstream release over it if --release is given (the HD cars, voice
#      packs and Remix mods), then this build's DLLs and ini over that;
#   4. writes the registry keys install.reg sets: rendername, videoname, lighting;
#   5. optionally installs DXVK's d3d9.dll for the prefix, which is the fastest
#      and most faithful Direct3D 9 on Linux (needs a Vulkan driver).
#
# Then: linux/run.sh [--prefix ...]
#
# RTX Remix itself (path tracing, the HD cars' PBR materials) is a Windows-only
# runtime with a 32-to-64-bit bridge; see linux/README.md for the state of
# running it under Wine. Without it the renderer draws the same 3D city, cars
# and the new camera views through plain Direct3D 9, lit by its own lamps.
set -euo pipefail

PREFIX="${WINEPREFIX:-$HOME/.local/share/gta2}"
GAME=""
FILES=""
RELEASE=""
DXVK=0
while [ $# -gt 0 ]; do
    case "$1" in
        --game) GAME="$2"; shift 2 ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        --files) FILES="$2"; shift 2 ;;
        --release) RELEASE="$2"; shift 2 ;;
        --dxvk) DXVK=1; shift ;;
        -h|--help) sed -n 2,30p "$0"; exit 0 ;;
        *) echo "unknown option $1" >&2; exit 1 ;;
    esac
done
[ -n "$GAME" ] || { echo "--game /path/to/GTA2 is required (the folder with gta2.exe)" >&2; exit 1; }
[ -f "$GAME/gta2.exe" ] || { echo "no gta2.exe in $GAME" >&2; exit 1; }
command -v wine >/dev/null || { echo "wine is not installed (needs 32-bit support: wine32 on Debian/Ubuntu)" >&2; exit 1; }

HERE="$(cd "$(dirname "$0")/.." && pwd)"
if [ -z "$FILES" ]; then
    if [ -d "$HERE/stage" ]; then FILES="$HERE/stage"
    else echo "no stage/ - run 'make' first, or give --files <unzipped release>" >&2; exit 1; fi
fi
[ -f "$FILES/gta2dx9.dll" ] || { echo "$FILES has no gta2dx9.dll" >&2; exit 1; }

export WINEPREFIX="$PREFIX"
export WINEARCH=win32
export WINEDEBUG="${WINEDEBUG:--all}"
echo "== Wine prefix: $WINEPREFIX (32-bit)"
mkdir -p "$WINEPREFIX"
wineboot -i >/dev/null 2>&1 || true

DEST="$WINEPREFIX/drive_c/Games/GTA2"
echo "== Copying the game to $DEST"
mkdir -p "$DEST"
cp -r "$GAME"/. "$DEST"/

if [ -n "$RELEASE" ]; then
    echo "== Unzipping the upstream release $RELEASE over it"
    command -v unzip >/dev/null || { echo "unzip is needed for --release" >&2; exit 1; }
    unzip -o -q "$RELEASE" -d "$DEST"
fi

echo "== Installing this build's DLLs and ini"
for f in gta2dx9.dll d3ddll.dll gta2dx9_vid.dll Dmavideo.dll DMAGlide.dll gta2dx9.ini install.reg uninstall.reg; do
    [ -f "$FILES/$f" ] && cp "$FILES/$f" "$DEST/$f"
done
# A player's own edits to gta2dx9.ini live in gta2dx9_settings.ini, which this never touches.
echo "== 3D models and high-resolution tiles"
rm -rf "$DEST/gta2dx9_models"; [ -d "$FILES/gta2dx9_models" ] && cp -r "$FILES/gta2dx9_models" "$DEST/"
rm -rf "$DEST/gta2dx9_textures_hd"; [ -d "$FILES/gta2dx9_textures_hd" ] && cp -r "$FILES/gta2dx9_textures_hd" "$DEST/"
echo "== Marking the installed gta2.exe large-address-aware (4 GB for the HD tiles; the original is untouched)"
sh "$HERE/linux/laa.sh" "$DEST/gta2.exe" || true

echo "== Registry: rendername, videoname, lighting, frame cap"
wine regedit /S "$(winepath -w "$DEST/install.reg" 2>/dev/null || echo "C:\\Games\\GTA2\\install.reg")" >/dev/null 2>&1 || \
    wine regedit /S "C:\\Games\\GTA2\\install.reg" >/dev/null 2>&1
# The intro movie goes through binkw32 on a DirectDraw surface the renderer
# replaces; the renderer draws it itself and reads this as a hint only.
wine reg add 'HKLM\SOFTWARE\DMA Design Ltd\GTA2\Screen' /v do_play_movie /t REG_DWORD /d 0 /f >/dev/null 2>&1 || true

if [ "$DXVK" = 1 ]; then
    echo "== DXVK"
    TMP="$(mktemp -d)"
    URL="$(curl -fsSL https://api.github.com/repos/doitsujin/dxvk/releases/latest | grep browser_download_url | grep 'dxvk-[0-9.]*\.tar\.gz' | head -1 | cut -d'"' -f4)"
    [ -n "$URL" ] || { echo "could not find the DXVK release download" >&2; exit 1; }
    curl -fsSL "$URL" -o "$TMP/dxvk.tar.gz"
    tar -xzf "$TMP/dxvk.tar.gz" -C "$TMP"
    cp "$TMP"/dxvk-*/x32/d3d9.dll "$WINEPREFIX/drive_c/windows/system32/d3d9.dll"
    wine reg add 'HKCU\Software\Wine\DllOverrides' /v d3d9 /t REG_SZ /d native,builtin /f >/dev/null 2>&1
    rm -rf "$TMP"
    echo "   DXVK's 32-bit d3d9.dll installed into the prefix (needs a Vulkan driver)."
fi

cat > "$WINEPREFIX/gta2-run.env" <<ENV
WINEPREFIX=$WINEPREFIX
GTA2_DIR=$DEST
ENV
echo
echo "Done. Start the game with:  linux/run.sh --prefix \"$PREFIX\""
echo "Press V in a level to cycle the classic, third-person and first-person views."
