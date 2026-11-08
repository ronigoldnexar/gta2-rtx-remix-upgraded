#!/usr/bin/env bash
# Serve deliverables/web (faststart mp4 copies + index.html) on port 8081, bound on all interfaces
# (reachable only from the firewall rule allow-jupyter-roni). Idempotent: exits if already running.
D=$(cd "$(dirname "$0")" && pwd); cd "$D/../deliverables/web" || exit 1
ss -tln | awk '{print $4}' | grep -q ':8081$' && exit 0
nohup setsid python3 "$D/videos_server.py" . 8081 >/tmp/gta2-videos-8081.log 2>&1 < /dev/null &
