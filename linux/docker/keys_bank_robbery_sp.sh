#!/usr/bin/env bash
# BANK ROBBERY (wil_ye2) with the shake-the-police skill (missions/bank_robbery_sp.py, SKILL-POLICE)
bash /work/to_level.sh
python3 /work/missions/bank_robbery_sp.py "$@"
touch /out/.keys_done
