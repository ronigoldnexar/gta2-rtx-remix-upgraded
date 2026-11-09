#!/usr/bin/env bash
# BANK ROBBERY (wil_ye2) with the guard fight by the kill_marked skill (SKILL-KILLMARK).
bash /work/to_level.sh
python3 /work/missions/bank_robbery_km.py "$@"
touch /out/.keys_done
