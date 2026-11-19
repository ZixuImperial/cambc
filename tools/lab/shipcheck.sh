#!/bin/sh
# shipcheck.sh CAND TAG [LANE=fix] [TRIGGER=list]: the fast gate in one command, then the submit on PASS (see shipcheck.py).
# DRY=1: everything except the submit and unrsets.sh.
cd /homes/zw4424/cambc || exit 2
exec python3 -I /homes/zw4424/cambc/tools/lab/shipcheck.py "$@"
