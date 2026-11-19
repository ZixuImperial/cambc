#!/bin/sh
# Condor job body of tools/lab/condab.py: condab_node.sh LISTFILE PAR [KEEPDIR|-] [MAPDIR]
# LISTFILE lines: "ID BOT_A BOT_B MAP" (bots and maps of the shared project /homes/USER/condor-work/proj400).
# Every game writes the platform statistics JSON, and condab.py --stat turns it into one "CQ {json}" line with the
# per-side metrics abl.sh's games.jsonl holds (gems, kills, deaths, earned gold, wards, treasure, fuel, bot faults).
# BUILD CACHE (29 Oct): building the two bots took ~35 s of every job (games ~10 s). Bots are now built once per node
# and source: a fixed node-local workspace /var/tmp/USER-cqws-<project stamp> holds bots/<name>-<source hash>, built
# under a per-bot flock and marked .built (CMake records absolute paths, so the path never changes); later jobs on
# that node reuse it. Cached builds unused for 12 h (2 days before 31 Oct) are removed at job start. Maps and outputs stay per job.
# KEEPDIR (condab.py KEEP=1): every game's replay and statistics go into one KEEPDIR/keep_<list>.tgz (rep/ID.repl26a,
# st/ID.json: the layout of KEEP=1 abl.sh), one file per job for the home's inode quota.
# MAPDIR (condab.py's on-the-fly maps): maps found there are taken from it instead of the shared project, and their
# games never keep a replay (the maps are not saved anywhere), unless KEEPDIR/.otf exists (condab OTF_KEEP, 3 Nov: inforead
# --keep-replays): then they keep the replay only (no statistics JSON, 0.95 MB a game). KEEPDIR/.rounds (digits, condab
# OTF_ROUNDS) caps the on-the-fly games at that many rounds (inforead --rounds: mechanism-only legs); saved-map games never.
# RUN (2 Nov): "run:SCRIPT" is a job other than games, routed through the pilot queue because pilots hold every slot (cqbatch.py and mergecheck.py): the script runs in
# a scratch dir with PAR as $1. Every pilot runs this file fresh per item, so old pilots can do it too.
case "$1" in run:*)
  W=$(mktemp -d /var/tmp/USER-run-XXXXXX); S=${1#run:}; cd "$W" || exit 1
  # JOBS FILE (6 Nov, home quota): run:FILE:OFFSET:LENGTH runs those bytes of one shared file, so a batch needs no script per item (cxefarm)
  case "$S" in *:[0-9]*:[0-9]*)
    L=${S##*:}; R=${S%:*}; O=${R##*:}; F=${R%:*}; S=$W/_job.sh
    tail -c +$((O + 1)) "$F" | head -c "$L" > "$S"
    [ "$(wc -c < "$S")" -eq "$L" ] || { echo "## jobs file $F short at $O+$L"; cd /; rm -rf "$W"; exit 2; } ;;
  esac
  sh "$S" "${2:-12}"; rc=$?
  cd /; chmod -R u+w "$W" 2>/dev/null; rm -rf "$W"
  echo "## end $(date -u +%T) rc $rc"; exit "$rc" ;;
esac
LIST=$1; PAR=${2:-12}; KEEP=$3; XMAPS=$4
[ "$KEEP" = "-" ] && KEEP=""
# PARTS FILE (2 Nov, off bitbucket): LIST may be PARTSFILE:INDEX, one file per run instead of one per part, for the home's inode quota.
LD=""
case "$LIST" in *:[0-9]*)
  LD=$(mktemp -d /var/tmp/USER-part-XXXXXX); PI=${LIST##*:}; PF=${LIST%:*}; LIST=$LD/part_$(printf %03d "$PI")
  awk -v i="$PI" '$1=="#part"{on=($2==i+0);next} on' "$PF" > "$LIST"
  [ -s "$LIST" ] || echo "MAP_MISSING part $PI of $PF is empty" ;;
esac
# CXE (4 Nov): PARTSFILE.cxe next to the parts file = play with cxe (tools/cxe) instead of the CLI: "rt DIR" (cxe with its own
# runtime: the pool runs Ubuntu 16-26, cxe needs glibc 2.38) and "bot NAME LIBRARY" lines; no bot builds on the node
CXE=""; [ -n "$PF" ] && [ -f "$PF.cxe" ] && CXE="$PF.cxe"
# 5 Nov: the bot libraries are built for x86-64-v3 (AVX2); on an older CPU (gpu24, Ivy Bridge) every cxe game died with
# "Illegal instruction" (48 games of cq_b1195L1_w2z_h2h_1 read as failed, and a sampled one as a spot-check mismatch).
# Such a node plays its part with the CLI instead (same games by definition, only slower).
if [ -n "$CXE" ] && ! grep -qw avx2 /proc/cpuinfo; then echo "## cxe skipped: this CPU has no AVX2, playing with the CLI"; CXE=""; fi
SRC=/homes/USER/condor-work/proj400
CLI=/homes/USER/condor-work/bin/cambc500
PY=/homes/USER/cambc/tools/lab/condab.py
export CAMBC_CACHE=/var/tmp/USER-cambc400-cache
. /homes/USER/cambc/tools/lab/cacheseed.sh  # 8 Nov: seed ninja/cmake/wasi-sdk from /homes (GitHub 504 broke node builds)
# COMPILE CACHE (30 Oct, Tool builder): the engine compiled both bots' WASM (~1 MB each) in every game, 3.5 of a game's
# ~4 CPU-s. CAMBC_WASMTIME_CACHE (an absolute dir; Wasmtime's cache keyed by module bytes, Wasmtime version and settings)
# compiles each bot once per node: a game then costs ~0.35 CPU-s, results identical (12/12 local games, same rounds).
export CAMBC_WASMTIME_CACHE=/var/tmp/USER-wtcache
BOTP=/homes/USER/condor-runs/botpacks  # 2 Nov: one tar per bot on the home (condab.py sync); no new files on bitbucket
BOTS_X=/vol/bitbucket/USER/proj400-bots  # read only: copies made before that, for items queued then
BC=/homes/USER/condor-work/buildcache  # the shared build cache (one tar per bot source and project stamp)
mkdir -p "$CAMBC_WASMTIME_CACHE"
STAMP=$(ls -ld --time-style=+%s "$SRC/cambc.toml" "$SRC/sdk" "$SRC/cmake" 2>/dev/null | awk '{print $6, $7}' | cksum | cut -d' ' -f1)
WS=/var/tmp/USER-cqws-$STAMP
J=/var/tmp/USER-condab-$$
mkdir -p "$J/maps" "$J/st" "$WS/bots" "$CAMBC_CACHE"
( flock 8
  if [ ! -f "$WS/.ready" ]; then
    rm -rf "$WS/sdk" "$WS/cmake"; cp -r "$SRC/cambc.toml" "$SRC/sdk" "$WS/" && { [ ! -d "$SRC/cmake" ] || cp -r "$SRC/cmake" "$WS/"; } && touch "$WS/.ready"
  fi
  # builds unused for 12 h go (31 Oct: was 2 days; HOST's /tmp is RAM and held 3.7 GB of them); a later job unpacks the
  # shared build cache tar or rebuilds
  find "$WS/bots" -mindepth 2 -maxdepth 2 -name .built -mmin +720 2>/dev/null | while read -r f; do rm -rf "$(dirname "$f")"; done
  # NODE CLEANUP (owner 30 Oct: keep deleting what is not needed, on Condor too): workspaces of older project stamps and
  # killed jobs' dirs untouched for 2 days / 1 day, compiled modules not written for 3 days (rebuilt in ~4 s if needed).
  find /var/tmp -maxdepth 1 -user "$(id -u)" -type d -name 'USER-cqws-*' ! -path "$WS" -mmin +2880 -exec rm -rf {} + 2>/dev/null
  find /var/tmp -maxdepth 1 -user "$(id -u)" -name 'USER-cqws-*.lock' ! -path "$WS.lock" -mmin +2880 -delete 2>/dev/null
  find /var/tmp -maxdepth 1 -user "$(id -u)" -type d -name 'USER-condab-*' ! -path "$J" -mmin +1440 -exec rm -rf {} + 2>/dev/null
  find "$CAMBC_WASMTIME_CACHE" -type f -mmin +4320 -delete 2>/dev/null
  find /var/tmp -maxdepth 1 -user "$(id -u)" -type d -name 'USER-part-*' -mmin +1440 -exec rm -rf {} + 2>/dev/null
) 8> "$WS.lock"
# 2 Nov: a pack is read over NFS once per node, whole, then maps are copied from /tmp. Reading it per map cost up to 480 MB an item (a 20 MB fresh set x 24 maps).
unpack() {  # unpack TAR -> the node's dir of its maps, on stdout
  u=/var/tmp/USER-mapc-$(printf %s "$1" | cksum | cut -d' ' -f1)
  if [ ! -f "$u/.done" ]; then
    ( flock 9; [ -f "$u/.done" ] || { mkdir -p "$u" && tar -xf "$1" -C "$u" && touch "$u/.done"; } ) 9> "$u.lock"
  fi
  touch "$u/.done" 2>/dev/null; touch "$u" 2>/dev/null
  echo "$u"
}
# 12 Nov (TB: lab helper /tmp is RAM-backed tmpfs; 3 h of map caches took 6.7 GB on HOST and stopped our pilots): 30 min, 5 min when /tmp < 2 GB free
MAPC_AGE=30; [ "$(df -Pm /var/tmp | awk 'NR==2{print $4}')" -lt 2000 ] 2>/dev/null && MAPC_AGE=5
find /var/tmp -maxdepth 1 -user "$(id -u)" \( -name 'USER-mapc-*' \) -mmin +$MAPC_AGE -exec rm -rf {} + 2>/dev/null
XU=""; [ -n "$XMAPS" ] && [ -f "$XMAPS.tar" ] && XU=$(unpack "$XMAPS.tar")
for m in $(awk '{print $4}' "$LIST" | sort -u); do
  if [ -n "$XMAPS" ] && [ -f "$XMAPS/$m.map26a" ]; then cp "$XMAPS/$m.map26a" "$J/maps/"
  # 30 Oct 23:40 (home quota): condab packs a batch's on-the-fly maps into ONE $XMAPS.tar; .xmap marks them (KEEP skips them)
  elif [ -n "$XU" ] && [ -f "$XU/$m.map26a" ]; then cp "$XU/$m.map26a" "$J/maps/"; touch "$J/maps/$m.xmap"
  elif [ -f "$SRC/maps/$m.map26a" ]; then cp "$SRC/maps/$m.map26a" "$J/maps/"
  else
    case $m in  # frozen bank maps (tools/lab/mapbank.py): from their 100-map pack, gen_bk_NNNNN -> gen_bk_NNN.tar
      gen_bk_?????|gen_bh_?????|gen_bk2_?????|gen_bh2_?????) p=${m%??}; cp "$(unpack "/homes/USER/condor-work/mapbank/$p.tar")/$m.map26a" "$J/maps/" ;;
      *) # ladder-weighted set (tools/lab/ladderw.py, 31 Oct): a packed map is found through the pack index
         p=$(awk -v m="$m" '$1==m {print $2; exit}' /homes/USER/condor-work/mapbank/lw_index.txt 2>/dev/null)
         if [ -n "$p" ]; then cp "$(unpack "/homes/USER/condor-work/mapbank/$p.tar")/$m.map26a" "$J/maps/"
         else cp "$SRC/maps/$m.map26a" "$J/maps/"; fi ;;
    esac
  fi
done
# 1 Nov: a map that did not arrive (removed from the shared project between sync and job start) is MAP_MISSING, apart from
# BUILD_FAIL; the warm build runs on the first map that is here, so a missing first map no longer reads as a failed build
mm=$(awk '{print $4}' "$LIST" | sort -u | while read -r m; do [ -f "$J/maps/$m.map26a" ] || printf '%s ' "$m"; done)
[ -n "$mm" ] && echo "MAP_MISSING $(echo $mm | wc -w) maps: $mm" | cut -c1-300
M1=$(awk '{print $4}' "$LIST" | while read -r m; do [ -f "$J/maps/$m.map26a" ] && { echo "$m"; break; }; done)
[ -n "$M1" ] || M1=$(awk 'NR==1{print $4}' "$LIST")
[ -n "$KEEP" ] && mkdir -p "$J/keep/rep" "$J/keep/st"
KOTF=""; RCAP=""
if [ -n "$KEEP" ]; then
  [ -f "$KEEP/.otf" ] && KOTF=1
  RCAP=$(tr -cd 0-9 < "$KEEP/.rounds" 2>/dev/null | cut -c1-5)
fi
echo "## host $(hostname) start $(date -u +%T)"
: > "$J/botmap"
[ -n "$CXE" ] && cat > "$J/cxegame.sh" <<CXEEOF
#!/bin/sh
# cxegame.sh ID A B MAP [--rounds N]: one game with cxe, statistics at J/st/ID.json, replay at J/rep_ID/g.repl26a
id=\$1; a=\$2; b=\$3; m=\$4; shift 4
rt=\$(awk '\$1=="rt"{print \$2}' "$CXE")
sa=\$(awk -v n="\$a" '\$1=="bot" && \$2==n {print \$3}' "$CXE"); sb=\$(awk -v n="\$b" '\$1=="bot" && \$2==n {print \$3}' "$CXE")
case "\$sa" in *.gz) sa="$J/lib/\$(basename "\$sa" .gz)";; esac
case "\$sb" in *.gz) sb="$J/lib/\$(basename "\$sb" .gz)";; esac
mkdir -p "$J/rep_\$id"
"\$rt/ld-linux-x86-64.so.2" --library-path "\$rt" "\$rt/cxe" "\$sa" "\$sb" "$J/maps/\$m.map26a" "$J/rep_\$id/g" "\$@" --statistics "$J/st/\$id.json"
CXEEOF
[ -n "$CXE" ] && echo "## cxe $(awk '$1=="rt"{print $2}' "$CXE")"
# bot libraries staged gzipped on the home (4 Nov: 168 plain ones were 510 MB of the 10 GB quota): unpack once per job, locally
[ -n "$CXE" ] && { mkdir -p "$J/lib"; awk '$1=="bot"{print $3}' "$CXE" | sort -u | while read L; do
  case "$L" in *.gz) gzip -dc "$L" > "$J/lib/$(basename "$L" .gz).tmp" && mv "$J/lib/$(basename "$L" .gz).tmp" "$J/lib/$(basename "$L" .gz)";; esac; done; }
[ -z "$CXE" ] && for b in $(awk '{print $2; print $3}' "$LIST" | sort -u); do
  (
    flock 7
    t="$WS/bots/.tmp-$b-$$"; rm -rf "$t"
    if [ -f "$BOTP/$b.tgz" ]; then
      for k in 1 2 3; do mkdir -p "$t" && tar -xzf "$BOTP/$b.tgz" -C "$t" && rm -f "$t/.srchash" && break; rm -rf "$t"; sleep 10; done
    else
      B0="$BOTS_X/$b"; [ -d "$B0/src" ] || B0="$SRC/bots/$b"
      for k in 1 2 3; do cp -r "$B0" "$t" && break; rm -rf "$t"; sleep 10; done
    fi
    h=$(cd "$t" && find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12)
    d="$WS/bots/$b-$h"
    if [ -f "$d/.built" ]; then
      rm -rf "$t"; touch "$d/.built"; echo "## cached $b-$h"
    else
      # SHARED BUILD CACHE (30 Oct, iteration-speed): one node's build of this source in this project stamp, as a tar at
      # the same absolute path (/var/tmp/USER-cqws-STAMP/bots/NAME-HASH): unpacking it skips the ~25-40 s build on every other
      # node. The warm run below still checks it (a stale or foreign build is simply rebuilt), so results never depend on it.
      rm -rf "$d"; BCT="$BC/$b-$h-$STAMP.tar"; from=""
      if [ -f "$BCT" ] && tar -xf "$BCT" -C "$WS/bots" 2>/dev/null && [ -d "$d/src" ]; then rm -rf "$t"; from=" (shared build cache)"; touch "$BCT" 2>/dev/null
      else rm -rf "$d"; mv "$t" "$d"; fi
      # 1 Nov: a warm build that failed without a compiler error (OOM "Killed", "Terminated", a full disk: 2 runs at 17h on
      # poplar04 lost a job each, and its games then rebuilt the half-built bot in parallel and were killed too) gets one retry
      wb() { (cd "$WS" && "$CLI" run "bots/$b-$h" "bots/$b-$h" --map "$J/maps/$M1.map26a" --rounds 1 --release -o "$J/warm" \
            --log-limit 0 > "$J/warm_$b.log" 2>&1); }
      if wb || { ! grep -qE "[0-9]+ errors? generated|map does not exist" "$J/warm_$b.log" && mv "$J/warm_$b.log" "$J/warm1_$b.log" \
            && echo "## retry build $b: $(grep -m1 -E 'Killed|Terminated|No space|Segmentation|signal' "$J/warm1_$b.log" | cut -c1-120)" \
            && sleep 20 && wb; }; then
        touch "$d/.built"; echo "## built $b-$h$from"
        if [ -z "$from" ] && [ ! -f "$BCT" ]; then
          mkdir -p "$BC" && tar -cf "$BC/.$b-$h-$STAMP.$$.tmp" --exclude .built -C "$WS/bots" "$b-$h" 2>/dev/null \
            && mv -f "$BC/.$b-$h-$STAMP.$$.tmp" "$BCT" || rm -f "$BC/.$b-$h-$STAMP.$$.tmp"
        fi
      elif grep -q "map does not exist" "$J/warm_$b.log"; then echo "MAP_MISSING warm map $M1 ($b not checked)"
      else e1=$(grep -m1 -E "Killed|Terminated|No space|Segmentation|signal [0-9]|fatal error|[0-9]+ errors? generated|:[0-9]+:[0-9]+: error" \
                 "$J/warm_$b.log" | cut -c1-200); [ -n "$e1" ] || e1=$(grep -m1 -iE "error" "$J/warm_$b.log" | cut -c1-200)
        echo "${e1:-see warm log}" > "$J/buildfail_$b"
        echo "BUILD_FAIL $b: ${e1:-no error line (see warm log)}"; tail -5 "$J/warm_$b.log"; fi  # 1 Nov: first compiler error
    fi
    echo "$b $b-$h" >> "$J/botmap"
  ) 7> "$WS/bots/.$b.lock"
done
echo "## built $(date -u +%T)"
cd "$WS" || exit 1
grep -v '^\s*$' "$LIST" | xargs -P "$PAR" -L 1 sh -c '
  id=$1; a=$2; b=$3; m=$4
  da=$(awk -v n="$a" "\$1==n{print \$2}" '"$J"'/botmap); db=$(awk -v n="$b" "\$1==n{print \$2}" '"$J"'/botmap)
  ox=""; { { [ -n "'"$XMAPS"'" ] && [ -f "'"$XMAPS"'/$m.map26a" ]; } || [ -f '"$J"'/maps/$m.xmap ]; } && ox=1
  ra=""; [ -n "$ox" ] && [ -n "'"$RCAP"'" ] && ra="--rounds '"$RCAP"'"
  if [ -n "'"$CXE"'" ]; then sh '"$J"'/cxegame.sh $id $a $b $m $ra > '"$J"'/log_$id 2>&1
  else '"$CLI"' run bots/$da bots/$db --map '"$J"'/maps/$m.map26a -o '"$J"'/rep_$id --log-limit 0 --release $ra --statistics '"$J"'/st/$id.json --json > '"$J"'/log_$id 2>&1; fi
  python3 -I '"$(dirname "$PY")"'/nodestat.py $id $a $b $m '"$J"'/st/$id.json || tail -3 '"$J"'/log_$id
  kp=""  # saved-map games: replay + statistics; on-the-fly games (KEEPDIR/.otf): the replay, even of a capped game (no statistics)
  if [ -n "'"$KEEP"'" ]; then if [ -n "$ox" ]; then [ -n "'"$KOTF"'" ] && kp=1; else [ -f '"$J"'/st/$id.json ] && kp=1; fi; fi
  if [ -n "$kp" ]; then
    rf=$(ls '"$J"'/rep_$id/*.repl26a 2>/dev/null | head -1)
    [ -n "$rf" ] && cp "$rf" '"$J"'/keep/rep/$id.repl26a && { [ -n "$ox" ] || cp '"$J"'/st/$id.json '"$J"'/keep/st/$id.json; }
  fi
  rm -rf '"$J"'/rep_$id '"$J"'/log_$id '"$J"'/st/$id.json
' _
if [ -n "$KEEP" ]; then
  tar czf "$KEEP/keep_$(basename "$LIST").tgz.tmp" -C "$J/keep" rep st && mv "$KEEP/keep_$(basename "$LIST").tgz.tmp" "$KEEP/keep_$(basename "$LIST").tgz"
  echo "## kept $(ls "$J/keep/rep" | wc -l) replays"
fi
echo "## end $(date -u +%T)"
cd / && chmod -R u+w "$J" 2>/dev/null; rm -rf "$J"; [ -n "$LD" ] && rm -rf "$LD"
