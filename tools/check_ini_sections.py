#!/usr/bin/env python3
"""Fails when an ini file repeats a section name.

Wine's GetPrivateProfileString reads only the first instance of a section, so a key in a
second [renderer] block silently keeps its default on Linux (defect
ini-second-renderer-section-ignored-under-wine, 9 Nov 2026). Run by `make check`.
usage: check_ini_sections.py <ini> [<ini> ...]"""
import re, sys

bad = 0
for path in sys.argv[1:]:
    seen = {}
    for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if not m:
            continue
        name = m.group(1).strip().lower()
        if name in seen:
            print(f"{path}:{n}: section [{name}] repeats the one at line {seen[name]} (Wine reads only the first)")
            bad += 1
        else:
            seen[name] = n
    print(f"{path}: {len(seen)} sections" + ("" if not bad else f", {bad} repeated"))
sys.exit(1 if bad else 0)
