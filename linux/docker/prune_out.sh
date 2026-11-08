#!/usr/bin/env bash
# Retention for run outputs: raw recordings (game.mp4), per-frame shot PNGs and run logs older than KEEP_HOURS
# are deleted; contact sheets (*sheet*.png), docs-referenced frames (out/quality_bar, out/*/m_*.png mission frames)
# and anything under deliverables/ are kept. Run from cron hourly.
KEEP_HOURS=${KEEP_HOURS:-48}
cd /home/roni_goldshmidt/gta2-linux/out || exit 1
find . -mindepth 2 -type f -name 'game.mp4' -mmin +$((KEEP_HOURS*60)) -delete
find . -mindepth 2 -type f -name 'shot_*.png' -mmin +$((KEEP_HOURS*60)) -delete
find . -mindepth 2 -type f \( -name '*.stdout' -o -name 'registry.txt' \) -mmin +$((KEEP_HOURS*60)) -delete
find . -mindepth 1 -type d -empty -mmin +$((KEEP_HOURS*60)) -delete 2>/dev/null
df -h /mnt/b200data | awk 'NR==2 {print "b200data used", $5}'
