#!/usr/bin/env bash
# FIX-ACTIONS-3 probe: warp to the wil pavement, third person punch, kerb-lane jack, drive off.
export DEMO_T0=$(date +%s.%N)
bash /work/to_level.sh
SKIP_START= python3 /work/fa3_demo.py
