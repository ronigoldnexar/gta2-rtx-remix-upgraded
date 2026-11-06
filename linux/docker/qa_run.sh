#!/usr/bin/env bash
# qa_run.sh <name> <seconds>: one QA scenario in its own container, devtools keys on.
cd "$(dirname "$0")/.."   # expects the ~/gta2-linux layout: gamerun/ (this folder as /work), game/, upstream-release/files, repo/stage, out/
N=$1; S=$2; rm -rf out/qa_$N; mkdir -p out/qa_$N
INI_SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/' \
docker run --rm --cpus=${QA_CPUS:-32} -e INI_SED -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" -v "$PWD/repo/stage:/stage:ro" -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/out/qa_$N:/out" -w /work gta2-remixbox bash /work/run_game.sh win32 $S 0 /work/keys_qa_$N.sh > out/qa_$N.run.log 2>&1
echo "qa_$N finished: $(grep -c FAULT out/qa_$N/gta2dx9.log 2>/dev/null) faults"; grep "CHECK\|RESULT\|done" out/qa_$N/keys.log | tail -4
