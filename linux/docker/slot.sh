#!/usr/bin/env bash
# Run a command inside one of the game-run slots; now a thin wrapper over runq.sh
# (a FIFO with priorities), kept for the scripts that call slot.sh. Usage: gamerun/slot.sh <command...>
exec "$(dirname "$0")/runq.sh" run -p "${PRIO:-5}" -n "${SLOT_NAME:-slot}" -- "$@"
