#!/usr/bin/env bash
# HOT DOG HOMICIDE! (Industrial file bil, bil_re1) in the street views: into the level, then the job runner
bash /work/to_level.sh
python3 /work/missions/hot_dog_homicide.py "$@"
touch /out/.keys_done
