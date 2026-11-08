#!/usr/bin/env bash
# REMIX-POST: the key library brings the game to the level, then remix_post.py plays
# the post-stack / time-of-day take (before and after at three spots).
# Needs INI_SED='s/^scene_key=.*/scene_key=F11/' (and SCENE_KEY=F11), Paused=1.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-45}
python3 /work/remix_post.py
mark done
