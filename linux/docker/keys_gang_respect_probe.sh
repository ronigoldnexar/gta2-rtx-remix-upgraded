#!/usr/bin/env bash
# SKILL-GUNFIGHT: check skills/gang_respect.exe in a running game (read, set the Loonies to 60, read back).
bash /work/to_level.sh
sleep 3
wine /work/skills/gang_respect.exe
wine /work/skills/gang_respect.exe loon 60
sleep 2
wine /work/skills/gang_respect.exe
DISPLAY=:99 ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/m_respect.png
touch /out/.keys_done
