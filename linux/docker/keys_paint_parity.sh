#!/usr/bin/env bash
# FIX-CAR-IDENTITY-4: the paint parity probe (docs/identity-system.md section 9.5). The player's stopped car, forced to
# each model in MODELS and painted as a sprite of each colour in PAINTS, shot from the classic camera's pose.
# Needs GTA2DX9_REGRESS_CAM=Z:\tmp\va2_cam.txt and VA2_CAM=/tmp/va2_cam.txt. Analyse with tools/paint_parity.py.
bash /work/to_level.sh
python3 /work/paint_parity_probe.py
