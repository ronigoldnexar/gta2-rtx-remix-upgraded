#!/usr/bin/env bash
# REMIX-SHOWCASE: the key library brings the game to the level, then remix_showcase2.py plays
# the showcase take (hours x spots, beacons at night, the showcase preset) for one district.
# Needs INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/',
# SCENE_KEY=F11, SETTINGS_SED Paused=1, RTX_EXTRA=/work/rtx_play.conf.extra.
. /work/remix_keys_lib.sh
# The library's to_level waits for "map wil.gmp is played"; with SWAP_LEVEL the line names the
# swapped district's map (ste.gmp, bil.gmp), so wait for any map line after the attract demo.
to_level() {
  local want=${SWAP_LEVEL:-wil}; [ -z "$want" ] && want=wil
  local n0; n0=$(grep -c "map $want.gmp is played" "$LOG" 2>/dev/null); n0=${n0:-0}   # the attract demo may have played it already
  for i in $(seq 1 60); do
    if [ "$(grep -c "map $want.gmp is played" "$LOG" 2>/dev/null)" -gt "$n0" ]; then sleep 8; echo "$(date +%T) level up after $i returns"; return 0; fi
    tap Return; sleep 4
  done
  echo "$(date +%T) level NOT reached"; return 1
}
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-30}
python3 /work/remix_showcase2.py
mark done
