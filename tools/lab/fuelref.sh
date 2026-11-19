#!/bin/sh
# fuelref.sh BOT [TAG]  (RC X904, Tool Builder 13 Nov): fuel cut-phase profile of BOT on the FIXED reference set /data/USER/st/fuelref
# (fresh/ = 120 non-hms maps v nova_spar_sbg, hms/ = 40 w_hms maps v itself), then RC's xfam.py and chains.py per run dir.
# Same maps every run, so version-to-version family deltas are code, not map draws. Output /data/USER/st/fuelref/runs/TAG (TAG default BOT).
# Runs itself as a memory-capped user unit (nova-fuelref-TAG) unless FUELREF_INNER=1. Exit 2 when the set's hashes do not match.
set -u
BOT=${1:?usage: fuelref.sh BOT [TAG]}
TAG=${2:-$BOT}
R=/data/USER/st/fuelref
REPO=/homes/USER/cambc
if [ "${FUELREF_INNER:-0}" != 1 ]; then
  [ -d "$REPO/bots/$BOT" ] || { echo "fuelref: no bots/$BOT" >&2; exit 1; }
  [ -e "$R/runs/$TAG" ] && { echo "fuelref: $R/runs/$TAG exists; pick another TAG" >&2; exit 1; }
  mkdir -p "$R/runs/$TAG"
  exec systemd-run --user --unit "nova-fuelref-$(printf %s "$TAG" | tr -c 'A-Za-z0-9_-' '_')" -p MemoryMax=8G --working-directory=$REPO \
    env FUELREF_INNER=1 nice -n 10 sh $REPO/tools/lab/fuelref.sh "$BOT" "$TAG"
fi
O=$R/runs/$TAG
cd $R && sha1sum -c --quiet SHA1SUMS > $O/sha1check.txt 2>&1 || { echo "FAIL sha1 $(date -u +%FT%TZ)" > $O/DONE; exit 2; }
cd $REPO
python3 -I tools/cxe/fuelprof.py "$BOT" --opp nova_spar_sbg --mapdir $R/fresh --maps 120 --top 60 --cutphase > $O/fuelprof_fresh.txt 2>&1
python3 -I tools/cxe/fuelprof.py "$BOT" --mapdir $R/hms --maps 40 --top 60 --cutphase > $O/fuelprof_hms.txt 2>&1
for f in fuelprof_fresh fuelprof_hms; do
  r=$(grep -o '/data/USER/st/cxe/fuelprof/[^)]*' $O/$f.txt | head -1 | xargs -r dirname)
  [ -n "$r" ] || continue
  python3 -I /data/USER/rulecheck/p6/x867/xfam.py "$r" "$BOT" > $O/xfam_$f.txt 2>&1
  python3 -I /data/USER/rulecheck/p6/x860/chains.py "$BOT" "$r" 5 > $O/chains_$f.txt 2>&1
done
echo "DONE $BOT $(date -u +%FT%TZ)" > $O/DONE
