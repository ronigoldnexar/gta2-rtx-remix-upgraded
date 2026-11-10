#!/bin/bash
# REMIX-PARITY-1: one rn_remix fixed-camera take on GPU 4 (VRAM sampled). usage: rp1_take.sh <name> <conf in gamerun> <secs> [docker -e ...]
N=$1; C=$2; S=$3; shift 3
cd /mnt/gta2/gta2-linux
SP=${SPOTS:-"13@169.6,127.5,2@third@178.5 127.8 3.2 167.9 127.5 2.5 0|170.9 127.3 3.1 167.9 127.5 2.5 0|classic;21.5@169.6,127.5,2@third@178.5 127.8 3.2 167.9 127.5 2.5 0|170.9 127.3 3.1 167.9 127.5 2.5 0"}
( while true; do echo "$(date +%s) $(nvidia-smi -i 4 --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits)"; sleep 5; done ) > /tmp/rp1_vram_$N.txt &
VP=$!
PRIO=1 SLOT_NAME=$N REMIX_NVCACHE=1 GTA2_GPU=4 STAGE=/mnt/gta2/gta2-linux/stage_rp1 gamerun/rn_remix.sh "$N" "$S" wil 13 "0,0,2" -e RTX_EXTRA=/work/$C -e GTA2DX9_STATE_EVERY=3 -e PROBE=rp1_cams.py -e "SPOTS=$SP" -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\frn9_cam.txt' -e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv' -e GTA2DX9_SCENE_NO_CAR=1 "$@"
kill $VP
cp /tmp/rp1_vram_$N.txt out/$N/vram.txt
echo TAKE_DONE $N
