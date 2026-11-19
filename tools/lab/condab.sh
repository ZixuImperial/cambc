#!/bin/sh
# Condor fan-out of a bot A/B (abl.sh + sprt.py + heldout.sh games): see tools/lab/condab.py.
# usage: sh tools/lab/condab.sh CAND BASE NAME [all|pool|fresh|heldout|MAPLIST]
exec nice -n 10 python3 -I /homes/zw4424/cambc/tools/lab/condab.py "$@"
