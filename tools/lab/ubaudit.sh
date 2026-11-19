#!/bin/sh
# One-command undefined-behaviour audit: CAND vs BASE under the v271 UBSan harness (/data/zw4424/st/audit).
# usage: sh tools/lab/ubaudit.sh CAND BASE [N]      (N mirror games per side, default 40 = 40 maps)
#   Builds instrumented copies (recoverable UBSan + float-divide-by-zero, libc++ hardening DEBUG, patch_pos.py map-bounds
#   checks), plays CAND vs CAND and BASE vs BASE on pool, gen_s, patho, gen_p, islands, gen_dom and gen_xing maps, collects
#   UB sites with ubx.py and prints `NEW UB SITES: k` (CAND sites absent in BASE, with file:line and values).
#   BASE's sites are cached per (base source, SEED, N, maps, FUEL, harness): an audit vs a cached base plays only CAND.
#   PASS = 0 new sites, 0 CAND traps / hardening asserts, 0 CAND bot faults. Exit 0 pass, 1 fail, 2 harness error.
#   All audits together run at most UBAUDIT_SLOTS (6) game or compile processes; each asks for JOBS (3).
#   env: JOBS (3), UBAUDIT_SLOTS (6), FUEL (1000000 a turn), SEED (1 = the same maps every audit), KEEP (1).
#   Outputs: /data/zw4424/st/audit/runs/CAND_STAMP/report.txt (+ run.log, rep/, ubx.txt); cache /data/zw4424/st/audit/ubcache.
#   Details: tools/lab/ubaudit.py's docstring.
[ -n "$2" ] || { echo "usage: sh tools/lab/ubaudit.sh CAND BASE [N]"; exit 2; }
STAMP=$(date -u +%Y%m%dT%H%M%SZ); export STAMP
exec nice -n 10 python3 -I /homes/zw4424/cambc/tools/lab/ubaudit.py "$@"
