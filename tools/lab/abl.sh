#!/bin/sh
# Local A/B test of two bots on this machine: every map, both sides. The fast path for testing; Condor
# (tools/condor/abtest.sh) is for massive sweeps only.
# usage: tools/lab/abl.sh BOT_A BOT_B NAME [MAPLIST] [REPEAT]
#   BOT_A/BOT_B: bot directories under bots/ in the repo. Their sources are copied into a private workspace,
#     so later edits to the repo copies do not affect a running test.
#   MAPLIST: file with one map name per line (default: the testing pool, 89 maps on 25 Oct 22:45: every map in the workspace
#     that is not generated (the 70 published maps = the ranked ladder's rotation, refreshed with `cambc maps pull`; the 4 pathological
#     ones; the Sprint 2 tournament maps S2-NN, except those the website publishes byte-identically under a ladder name: all 15 are
#     02* maps since 25 Oct, so they play once, under the ladder name) plus the custom maps gen_c_* (the 15 insane maps,
#     tools/lab/geninsane.py); never the generated families gen_s/gen_p/gen_u/gen_g*/gen_i/gen_NN).
#     Held-out generated maps: tools/lab/heldout.sh. Playbook slices:
#     /homes/USER/condor-work/teams/pb2/maplists/*.txt; pathological maps: /data/USER/patho4.txt.
#   REPEAT: games per map and side (default 1; repeats only differ if the bots use randomness).
# Games run through `cambc run-batch` with JOBS runner processes (default 12) and the platform's
# statistics JSON for every game, inside one fixed project directory ($PROJ): a cached bot build records the
# project's absolute cmake path, so that path must never change between runs. Only one A/B runs at a time (flock on /data/USER/abl.lock), so concurrent
# callers queue instead of oversubscribing the 16 cores.
# Outputs in /data/USER/abl/NAME: games.list, games.jsonl (per-game metrics), run/job_0.out (absum.py format),
# summary.txt. KEEP=1 also keeps the replays (rep/) and statistics (st/).
# The summary (tools/lab/ablsum.py): wins, gems and gem share, kills, deaths, earned gold, wards, Treasure
# emblems, fuel exhaustions and bot faults per side, then wins per map slice and per map; with KEEP=1 also the
# mechanism table (tools/lab/mech.py: time budget, opening, captures, sorties, banking, deaths; MECH=0 skips it).
set -e
renice -n 10 $$ >/dev/null 2>&1 || true  # bulk games yield to sessions (CLAUDE.md: machine load); a no-op when already niced
REPO=/homes/USER/cambc; CLI=${ABL_CLI:-/data/USER/cambc500/bin/cambc500}
# COMPILE CACHE (30 Oct): each bot's WASM is compiled once, not in every game (~4 -> ~0.35 CPU-s a game; same results)
export CAMBC_WASMTIME_CACHE=${CAMBC_WASMTIME_CACHE:-/data/USER/wtcache}; mkdir -p "$CAMBC_WASMTIME_CACHE"
# Default: cambc 5.0.0 = engine 3.0.0 (finals patch; default since 4 Nov ~23:45Z; before that 4.0.0 = engine 2.0.0, 3.0.4 earlier).
# ABL_CLI picks another engine's client (e.g. /homes/USER/condor-work/bin/cambc304 = the old engine). Every CLI but 3.0.4 gets
# its own base (SDK), project and build cache, suffixed by its version, and each run records its CLI in cli.txt, so
# tools/lab/abindex.py never mixes games of two engines.
CV=$("$CLI" --version 2> /dev/null | awk '{print $2}'); [ -n "$CV" ] || { echo "abl.sh: $CLI does not run"; exit 1; }
SUF=$([ "$CV" = 3.0.4 ] || echo "_$CV"); [ "$CV" = 5.0.0 ] && SUF=_4.0.0  # 4 Nov finals patch: 5.0.0 builds the same wasm, so it shares 4.0.0's project, map bank and build cache (cli.txt still keeps the engines apart)
BASE=${ABL_BASE:-/data/USER/work301$SUF}
A=$1; B=$2; NAME=$3; ML=$4; REP=${5:-1}; JOBS=${JOBS:-12}
[ -n "$NAME" ] || { echo "usage: abl.sh BOT_A BOT_B NAME [MAPLIST] [REPEAT]"; exit 1; }
# NAME becomes a path that is rm -rf'ed below: a plain name only (a '/' could reach outside the run dir, a leading '.'
# hides the run from tools/lab/abindex.py, a space breaks the manifest)
case $NAME in .*|*[!A-Za-z0-9._+-]*) echo "abl.sh: NAME must be a plain run name ([A-Za-z0-9._+-], no leading '.'): $NAME"; exit 1 ;; esac
for b in "$A" "$B"; do [ -d "$REPO/bots/$b/src" ] || { echo "no bot $b"; exit 1; }; done
# Two names, one bot: most bots/ entries are symlinks into /data/USER/st/*/bots, and a `cp -r` of one copies the link, so an
# edit meant for a test copy lands in the original (27 Oct: idle_v238 -> the live v238 dir, the run played idle vs idle).
# Refuse an A/B whose two different names resolve to the same directory or the same sources; ABL_SAME=1 allows it.
srch() { (cd "$REPO/bots/$1" && find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12); }
HA=$(srch "$A"); HB=$(srch "$B"); RA=$(readlink -f "$REPO/bots/$A"); RB=$(readlink -f "$REPO/bots/$B")
if [ "$A" != "$B" ] && [ -z "$ABL_SAME" ] && { [ "$RA" = "$RB" ] || [ "$HA" = "$HB" ]; }; then
  echo "abl.sh: $A and $B are the same bot ($RA = $RB, sources $HA = $HB); copy the real dir first (tools/lab/newbot.sh), or ABL_SAME=1"; exit 1
fi
echo "## bots: $A $HA $RA | $B $HB $RB"
OUT=/data/USER/abl/$NAME; PROJ=${ABL_PROJ:-/data/USER/ablproj$SUF}; CACHE=${ABL_CACHE:-/data/USER/ablcache2$SUF}
# A rerun of the same NAME waits until the previous one has finished, summary and clean-up included: its rm -rf would
# otherwise delete the outputs of games still being played and swap games.list under the running summary.
mkdir -p /data/USER/abl/.locks
exec 8> "/data/USER/abl/.locks/$NAME"
flock -n 8 || { echo "## $NAME: waiting for the previous run of the same name to finish"; flock 8; }
rm -rf "$OUT"; mkdir -p "$OUT/run" "$OUT/rep" "$OUT/st" "$PROJ" "$CACHE"
echo "cambc $CV" > "$OUT/cli.txt"
printf '%s %s %s\n%s %s %s\n' "$A" "$HA" "$RA" "$B" "$HB" "$RB" > "$OUT/bots.txt"
# Each bot version is built once: its sources are copied to $CACHE/<bot>-<hash of src/>, where run-batch builds
# them in place on first use (a built directory must never move: CMake records its absolute path).
cached() {
  h=$(cd "$REPO/bots/$1" && find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12)
  d=$CACHE/$1-$h
  if [ ! -d "$d/src" ]; then
    t=$d.tmp.$$; rm -rf "$t"; rsync -a --exclude .cambc --exclude build "$REPO/bots/$1/" "$t/"
    mv -T "$t" "$d" 2> /dev/null || rm -rf "$t"
  fi
  echo "$d"
}
DA=$(cached "$A"); DB=$(cached "$B")
# The default list leaves out the generated families (gen_*, except the custom gen_c_* maps), so held-out batches stay
# unspent; tools/lab/heldout.sh runs the held-out set (list /data/USER/genmaps/maplist.txt). On 25 Oct the pool grew
# from 44 to 89 maps (owner: every map plus the website's new ones), so A/Bs from before and after are not comparable. At 22:45
# the website's 15 new 02* maps turned out to be the Sprint 2 maps: still 89 maps, the S2 copies now under the ladder names.
# A Sprint 2 map S2-NN with a byte-identical published copy (02*) in the same workspace plays once, under the ladder name
# (the S2-NN files stay for S2 lists and ABL_BASE workspaces without the copies).
dup_s2() { for s in "$BASE"/maps/S2-*.map26a; do [ -f "$s" ] || continue; for p in "$BASE"/maps/02*.map26a; do [ -f "$p" ] && cmp -s "$s" "$p" && { basename "$s" .map26a; break; }; done; done; }
if [ -n "$ML" ]; then MAPS=$(grep -v '^\s*$' "$ML"); else DUP=" $(dup_s2 | tr '\n' ' ') "; MAPS=$( (ls "$BASE/maps" | grep '\.map26a$' | grep -v '^gen_'; ls "$BASE/maps" | grep '^gen_c_.*\.map26a$') | sed 's/\.map26a$//' | while read -r m; do case "$DUP" in *" $m "*) ;; *) echo "$m" ;; esac; done); fi
: > "$OUT/games.list"; : > "$OUT/manifest.txt"; id=0
for m in $MAPS; do
  [ -f "$BASE/maps/$m.map26a" ] || { echo "no map $m"; continue; }
  i=0
  while [ $i -lt "$REP" ]; do
    for pair in "$A $DA $B $DB" "$B $DB $A $DA"; do
      set -- $pair; id=$((id+1))
      echo "$id $1 $3 $m" >> "$OUT/games.list"
      echo "$2 $4 $PROJ/maps/$m.map26a $OUT/rep/$id.repl26a --statistics $OUT/st/$id.json --json" >> "$OUT/manifest.txt"
    done
    i=$((i+1))
  done
done
echo "## $NAME: $id games queued $(date +%T)"
exec 9> "${ABL_LOCK:-/data/USER/abl.lock}"
flock 9
echo "## $NAME: started $(date +%T)"
# Refresh the fixed project in place (rsync keeps unchanged files untouched, so cached builds stay valid).
rsync -a "$BASE/cambc.toml" "$PROJ/cambc.toml"
for d in maps sdk cmake; do [ -d "$BASE/$d" ] && rsync -a "$BASE/$d/" "$PROJ/$d/"; done
cd "$PROJ"
if ! "$CLI" run-batch "$OUT/manifest.txt" --jobs "$JOBS" --release --log-limit 0 > "$OUT/run.log" 2>&1; then
  echo "RUN_FAIL (full log: $OUT/run.log)"; grep -iE "error|fail" "$OUT/run.log" | head -20
fi
flock -u 9
echo "## $NAME: finished $(date +%T)"
python3 -I "$REPO/tools/lab/ablsum.py" "$OUT" "$A" "$B" | tee "$OUT/summary.txt"
ok=$(ls "$OUT/st" 2> /dev/null | wc -l)
[ "$ok" -lt "$id" ] && echo "!! WARNING: only $ok of $id games produced results; the rest FAILED (see $OUT/run.log). Do not read missing games as draws."
[ "$KEEP" = 1 ] || rm -rf "$OUT/rep" "$OUT/st"
