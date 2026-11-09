#!/usr/bin/env bash
# SKILL-ROOFTOP: a rooftop-phone job played with skills/rooftop_access.py (climb on foot, no warp).
# ROOF_JOBS (default wil_ze1) names the job(s).
bash /work/to_level.sh
python3 /work/skills/rooftop_access.py ${ROOF_JOBS:-wil_ze1}
touch /out/.keys_done
