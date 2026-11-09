#!/usr/bin/env bash
# BLOW JOB! (Residential, ste_re1) with its own runner, gamerun/missions/blow_job.py
python3 /work/missions/blow_job.py "$@"
touch /out/.keys_done
