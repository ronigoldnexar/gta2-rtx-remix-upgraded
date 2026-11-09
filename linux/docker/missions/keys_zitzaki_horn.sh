#!/usr/bin/env bash
# GET ZITZAKI (Downtown, wil_ye1) with the horn stop played by skills/horn_pickup.py (SKILL-HORN)
bash /work/to_level.sh
python3 /work/missions/zitzaki_horn.py "$@"
touch /out/.keys_done
