#!/usr/bin/env bash
# BEV parity check: into the level, then gamerun/bev_parity.py (switch moments in every
# view, the same walk in every view, live code diffs). Analyse with tools/bev_parity.py.
bash /work/to_level.sh
python3 /work/bev_parity.py
touch /out/.keys_done
