#!/usr/bin/env bash
# VEHICLE-FEEL highlight clip from vehfeel_take.py's per-phase recordings (clip_day/night/wreck.mp4):
#   vehfeel_clip.sh <out mp4> <day clip> <start> <len> <night clip> <start> <len> <wreck clip> <start> <len>
# out/vehicle_feel.mp4 was: vf_6/clip_day.mp4 0 12, vf_6/clip_night.mp4 0 8, vf_8/clip_wreck.mp4 2.6 7.
set -e
OUT=$1; FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
cap() { echo "drawtext=fontfile=$FONT:text='$1':x=24:y=h-56:fontsize=30:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=10"; }
nice -n 15 ffmpeg -v error -y -ss "$3" -t "$4" -i "$2" -ss "$6" -t "$7" -i "$5" -ss "$9" -t "${10}" -i "$8" \
  -filter_complex "[0:v]fps=25,scale=1280:720,$(cap 'Vehicle feel - launch, brake, reverse, turn, handbrake marks')[a];[1:v]fps=25,scale=1280:720,$(cap 'Night - lamp pools, brake and reverse lamps, exhaust')[b];[2:v]fps=25,scale=1280:720,$(cap 'Blown up - debris and sparks')[c];[a][b][c]concat=n=3:v=1:a=0[v]" \
  -map "[v]" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "$OUT"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT"
