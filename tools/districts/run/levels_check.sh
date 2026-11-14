# levels_check.sh: the ship level-change check, 3 processes x 2 laps, plain (fixed and the 5090 DLL) and L4 Remix
G=/mnt/gta2/gta2-linux; R=$G/wt_districts; W=$G/districts_work
# stop the previous (stuck) level runs' containers: only mine (their out dirs are dkl2_*)
for c in $(sudo -n docker ps -q); do sudo -n docker inspect $c --format '{{range .Mounts}}{{.Source}} {{end}}' | grep -q 'out/dkl2_' && sudo -n docker stop -t 3 $c > /dev/null && echo "stopped $c"; done
sleep 5
sed 's#STAGE=\$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=0#STAGE=$G/stage_districts_old GTA2_DIRECT_KEYS=1 FPS=0#' $R/tools/districts/run/levels_run.sh > $W/levels_run_old.sh
( for p in 1 2 3; do LAPS=2 bash $R/tools/districts/run/levels_run.sh dkl3_plain_$p; done > $W/dkl3_plain.log 2>&1 ) &
sleep 90
( for p in 1 2 3; do LAPS=2 bash $W/levels_run_old.sh dkl3_old_$p; done > $W/dkl3_old.log 2>&1 ) &
sleep 90
( for p in 1 2 3; do LAPS=2 bash $R/tools/districts/run/levels_run.sh dkl3_remix_$p remix; done > $W/dkl3_remix.log 2>&1 ) &
wait
for f in dkl3_plain dkl3_old dkl3_remix; do grep 'FAULT' $W/$f.log; done
for r in $(ls -d $G/out/dkl3_* | xargs -n1 basename); do echo "$r: $(grep -a 'facade kit stream C' $G/out/$r/gta2dx9.log 2>/dev/null | sed 's/.*gta2dx9_districts.//' | cut -c1-3 | tr '\n' ' ')"; done
echo lvl11 done
