#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/
# The devtools scene warp needs scene_key bound before the game starts (the DLL reads it once);
# F11, not F10 (Wine's menu-key handling eats every other F10). run_game*.sh applies these lines.
export SCENE_KEY=F11
python3 /work/vr_walk.py
