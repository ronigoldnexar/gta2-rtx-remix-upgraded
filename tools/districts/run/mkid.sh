# mkid.sh <prefix(dki|dkri)> <tag> <out jpg> [on|off]: the 3 districts side by side, day and dusk, drive and drive_rev
PFX=$1; TAG=$2; OUT=$3
O=/mnt/gta2/gta2-linux/out; K=${4:-on}; a=()
for pose in drive drive_rev; do for t in day dusk; do for l in "wil local_nav_m31 Downtown-core" "ste gang_sciegang Residential-brownstone" "bil nav_m14 Industrial-docks"; do
  set -- $l; a+=("$3 $t $pose kit $K" $O/${PFX}_$1_$TAG/dk_$1_$2_${t}_${pose}_$K.png); done; done; done
/mnt/gta2/gta2-linux/vreg/venv/bin/python /mnt/gta2/gta2-linux/wt_districts/tools/districts/run/grid.py $OUT 3 640 "${a[@]}"
