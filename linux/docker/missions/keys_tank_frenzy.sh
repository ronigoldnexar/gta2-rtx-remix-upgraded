#!/usr/bin/env bash
# Downtown tank kill frenzy (TANK_FRENZY=wil_kf08|wil_kf07) with the Wave M tank skill.
bash /work/to_level.sh
python3 /work/missions/tank_frenzy.py "$@"
touch /out/.keys_done
