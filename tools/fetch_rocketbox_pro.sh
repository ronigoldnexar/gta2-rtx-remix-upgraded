#!/usr/bin/env bash
# Fetch Rocketbox avatars from any category (Adults or Professions): the export
# FBX and the colour textures, then convert to glb with FBX2glTF. MIT licence.
# Usage: fetch_rocketbox_pro.sh <Adults|Professions> <name>...
set -e
cd "$(dirname "$0")/rocketbox"
CAT=$1; shift
RAW=https://raw.githubusercontent.com/microsoft/Microsoft-Rocketbox/master/Assets/Avatars/$CAT
API=https://api.github.com/repos/microsoft/Microsoft-Rocketbox/contents/Assets/Avatars/$CAT
for name in "$@"; do
  mkdir -p "$name"; cd "$name"
  [ -f "$name.fbx" ] || curl -sfL -o "$name.fbx" "$RAW/$name/Export/$name.fbx"
  for tex in $(curl -sf "$API/$name/Textures" | python3 -c "import json,sys; print(' '.join(x['name'] for x in json.load(sys.stdin) if x['name'].endswith('_color.tga')))"); do
    [ -f "$tex" ] || curl -sfL -o "$tex" "$RAW/$name/Textures/$tex"
  done
  [ -f "$name.glb" ] || ../../tools/FBX2glTF-linux-x64 -i "$name.fbx" -o "$name" --binary > /dev/null 2>&1 || true
  ls -la "$name.glb" 2>/dev/null | awk -v n="$name" '{print n, $5}' || echo "$name FAILED"
  cd ..
done
