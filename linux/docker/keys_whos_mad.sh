#!/usr/bin/env bash
# WHO'S MAD? (wil_lm1) with the hitmen fought by the gunfight skill (SKILL-GUNFIGHT).
bash /work/to_level.sh
python3 /work/missions/whos_mad.py "$@"
touch /out/.keys_done
