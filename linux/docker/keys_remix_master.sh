#!/usr/bin/env bash
# The master demo under RTX Remix: the key library brings the game to the level
# (prewarm, attract demo, Downtown), then final_demo2.py plays the take: classic
# opening, third person, first person, a car entered at the kerb, the drive in
# chase / driver's seat / classic, out, the tutorial phone. The game clock runs
# (SETTINGS_SED), so a take started at dusk ends at night with the lamps lit.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-60}
SKIP_START=1 python3 /work/final_demo2.py
mark done
