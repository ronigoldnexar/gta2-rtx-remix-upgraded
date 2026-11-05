#!/bin/sh
# Marks a 32-bit Windows executable large-address-aware, in place.
#
# GTA2 is a 2 GB process by default. Marking the installed copy of gta2.exe
# large-address-aware lets Wine give it 4 GB of address space on a 64-bit
# kernel, which is what the 512 px block-compressed tile set and the 3D models
# need. Only the copy inside the Wine prefix is touched, never the original.
# Pure POSIX shell plus od and dd, so it runs inside any container.
set -e
exe="$1"
[ -f "$exe" ] || { echo "laa.sh: no such file: $exe" >&2; exit 1; }
# e_lfanew at 0x3C (little-endian u32) -> PE header; Characteristics is at PE+0x16 (u16).
pe=$(od -An -t u4 -j 60 -N 4 "$exe" | tr -d ' ')
sig=$(od -An -c -j "$pe" -N 2 "$exe" | tr -d ' ')
[ "$sig" = "PE" ] || { echo "laa.sh: $exe is not a PE file" >&2; exit 1; }
off=$((pe + 22))
lo=$(od -An -t u1 -j "$off" -N 1 "$exe" | tr -d ' ')
if [ $((lo & 32)) -ne 0 ]; then echo "laa.sh: $exe is already large-address-aware"; exit 0; fi
lo=$((lo | 32))
printf "$(printf '\\%03o' "$lo")" | dd of="$exe" bs=1 seek="$off" count=1 conv=notrunc status=none
echo "laa.sh: $exe marked large-address-aware (Characteristics byte at $off: $lo)"
