#!/bin/sh
# Session-start health check for the cambc lab: run it first in every session (and after any machine move).
# usage: sh tools/lab/doctor.sh [--net] [--from HOST]   (--net also asks PyPI for a newer cambc; --from HOST: after a machine move, list
#        every script (*.py, *.sh) and build workspace (cambc.toml) under /data/zw4424 on HOST that this machine lacks, with the copy line)
# Read-only, except that it records this machine's name in /homes/zw4424/condor-work/.lasthost.
# Checks: machine move (per-machine /data and /tmp), the toolchain link, home-dir inode and byte quota, Kerberos
# ticket (Condor and ssh need it), Condor jobs of this account, who holds or waits for the A/B lock, /tmp space,
# local vs platform engine version, and the installed test map families. Lines start with OK, WARN or FAIL.
ARGS="$*"  # 10 Nov: saved first, because the quota check's 'set --' replaces "$@" (so --net never worked before)
REPO=/homes/zw4424/cambc; LAST=/homes/zw4424/condor-work/.lasthost; H=$(hostname)
ok() { echo "OK   $*"; }; warn() { echo "WARN $*"; }; fail() { echo "FAIL $*"; }

prev=$(cat "$LAST" 2> /dev/null)
if [ -z "$prev" ] || [ "$prev" = "$H" ]; then ok "machine $H"
else warn "machine changed: $prev -> $H. /data and /tmp are per machine: copy what you need with"
  echo "       rsync -a -e 'ssh -o BatchMode=yes' $prev:/data/zw4424/ /data/zw4424/   (big result dirs: fetch on demand)"
  echo "       (only if $prev holds the NEWEST pipeline state: compare its st/bq/live.txt first)"; fi
echo "$H" > "$LAST" 2> /dev/null

[ -d /data/zw4424 ] && ok "/data/zw4424 present ($(df -h /data | awk 'NR==2 {print $4}') free)" || fail "no /data/zw4424: mkdir -p /data/zw4424"
c=$(readlink "$HOME/.cache/cambc")
if [ -n "$c" ] && [ -d "$c" ]; then ok "toolchain cache ~/.cache/cambc -> $c"
else fail "~/.cache/cambc must link to local disk: rm -f ~/.cache/cambc && mkdir -p /data/zw4424/cambc-cache && ln -s /data/zw4424/cambc-cache ~/.cache/cambc"; fi
[ -d /data/zw4424/work301/maps ] && ok "abl.sh workspace /data/zw4424/work301 ($(ls /data/zw4424/work301/maps | grep -vc '^gen_') pool maps)" \
  || fail "no abl.sh workspace /data/zw4424/work301 (copy it from the previous machine)"
# 10 Nov (TB, maple18 -> maple20): the move skipped these as "caches"; every armq trunk build then failed (mergecheck, pilotbuild, flip.sh)
# 10 Nov (Deep): st/cxe/proj (puppet --diag) and the rswproj seed (mergecheck.setup_ws) were missing too
for w in /data/zw4424/mergecheck/ws /data/zw4424/trunkproj /data/zw4424/ablproj_4.0.0 /data/zw4424/st/cxe/proj /data/zw4424/rswproj; do
  [ -f "$w/cambc.toml" ] && [ -d "$w/sdk" -o "$w" = /data/zw4424/ablproj_4.0.0 ] && ok "build workspace $w" \
    || fail "build workspace $w incomplete (needs cambc.toml, cmake/, sdk/, bots/): copy them from the previous machine"; done
[ -x /usr/local/condor/release/bin/condor_submit ] && ok "Condor client /usr/local/condor/release/bin" || fail "no Condor client in /usr/local/condor/release/bin"

# quota -s columns shift when a soft limit is exceeded (a '*' and a grace column appear), so classify fields by shape:
# sizes end in K/M/G/T, file counts are bare integers, grace periods contain letters or ':'.
set -- $(python3 -I "$(dirname "$0")/homequota.py" 2> /dev/null)  # 1 Nov: the HOME server's line (quota -s also lists other mounted servers)
if [ $# -eq 5 ]; then
  files=$1; fsoft=$2; fhard=$3; bytes=$4; bsoft=$5
  msg="home quota: $files of $fsoft files (hard $fhard), ${bytes}M of ${bsoft}M"
  if [ "$files" -ge 59000 ] || [ "$bytes" -ge "$bsoft" ]; then fail "$msg: CRITICAL, Claude sessions, git and builds break at the hard limit. Archive old bots/ variants and condor-runs/ to single tarballs"
  elif [ "$files" -ge 55000 ] || [ "$bytes" -ge $((bsoft * 95 / 100)) ]; then warn "$msg: near the limits (keep inodes under 55k; never write per-game files to /homes)"
  else ok "$msg"; fi
else warn "could not read quota"; fi

if klist -s 2> /dev/null; then ok "Kerberos ticket valid until $(klist 2> /dev/null | awk '/krbtgt/ {print $3, $4; exit}')"
else warn "no valid Kerberos ticket: Condor and ssh to other lab machines fail until the owner logs in again (never run kinit yourself)"; fi

export PATH=/usr/local/condor/release/bin:$PATH
if command -v condor_q > /dev/null; then
  s=$(timeout 20 condor_q -af JobStatus 2> /dev/null | sort | uniq -c | awk '{n[$2]=$1} END {printf "idle %d, running %d, held %d, suspended %d", n[1], n[2], n[5], n[7]}')
  case "$s" in *"held 0"*) ok "Condor jobs of this account: $s" ;; *) warn "Condor jobs of this account: $s (condor_q -hold; condor_rm stuck jobs)" ;; esac
fi

pids=$(fuser /data/zw4424/abl.lock 2> /dev/null)
if [ -z "$pids" ]; then ok "A/B lock /data/zw4424/abl.lock free"
else
  for p in $pids; do a=$(ps -o args= -p "$p" 2> /dev/null); case "$a" in *abl.sh*) echo "     lock user: pid $p, up $(ps -o etime= -p "$p" | tr -d ' '): $a" ;; esac; done
  ok "A/B lock in use (abl.sh queues: one A/B plays at a time)"
fi

t=$(df /tmp | awk 'NR==2 {print $5}' | tr -d %)
[ "$t" -lt 80 ] && ok "/tmp ${t}% used" || warn "/tmp ${t}% used (tmpfs: old scratch dirs fill it)"

loc=$(ls -t /data/zw4424/abl/*/st/*.json 2> /dev/null | head -1)
plat=""; pf=""
for d in $(ls -td /data/zw4424/plat/*/ 2> /dev/null); do  # newest set with a downloaded match
  pf=$(ls "$d" | grep -E '^[0-9a-f-]{36}\.json$' | head -1); [ -n "$pf" ] && { plat=$d; break; }
done
lv=$([ -n "$loc" ] && python3 -I -c "import json,sys; print(json.load(open(sys.argv[1]))['match']['engineVersion'])" "$loc" 2> /dev/null)
pv=$([ -n "$pf" ] && python3 -I -c "import json,sys; print(json.load(open(sys.argv[1]))['match']['engineVersion'])" "$plat$pf" 2> /dev/null)
if [ -n "$lv" ] && [ -n "$pv" ]; then
  if [ "$lv" = "$pv" ]; then ok "engine: local $lv = platform $pv"
  elif [ "$lv" = 1.0.2 ] && [ "$pv" = 1.0.3 ]; then ok "engine: local $lv, platform $pv (checked 2026-10-22: 12 games identical on both)"
  else warn "engine: local $lv, platform $pv (newest set $(basename "$plat")): replay a few games on both before trusting local results"; fi
else echo "--   engine versions unknown (no local statistics kept or no live set downloaded)"; fi
if echo " $ARGS " | grep -q ' --net '; then
  v=$(timeout 30 python3 -m pip index versions cambc 2> /dev/null | sed -n 's/^cambc (\(.*\))/\1/p')
  [ -n "$v" ] && echo "--   newest cambc on PyPI: $v (local CLI: $(/data/zw4424/cambc400/bin/cambc400 --version 2> /dev/null))"
fi

M=/data/zw4424/work301/maps
ok "test maps: $(ls $M | grep -vc '^gen_') pool, $(ls $M | grep -c '^gen_[0-9]') held-out (gen_NN), $(ls $M | grep -c '^gen_dev_') dev, $(ls $M | grep -c '^gen_s_') fresh (gen_s_), $(ls $M | grep -c '^gen_p_') generated pathological (gen_p_), $(ls $M | grep -c '^gen_c_') custom (gen_c_)"
[ "$(ls $M | grep -c '^gen_s_')" -ge 400 ] || warn "fresh maps missing: python3 tools/lab/genbig.py --install (and --family patho --install)"

# 10 Nov (Tool Builder, after maple18 -> maple20): the move copied a chosen list, and 923 reader scripts in st/bNNN/*, st/cxe/proj and
# st/b746/py/repl2map.py stayed behind. Read-only on HOST; prints what is missing and the rsync line, copies nothing.
for a in $ARGS; do [ "$prevarg" = --from ] && FROM=$a; prevarg=$a; done
if [ -n "$FROM" ]; then
  Q="find /data/zw4424 -maxdepth 6 \\( -path '*/mergecheck/builds' -o -path '*/condor_runs_archive' -o -path '*/readmany/runs' -o -path '*/trunkproj/bots' -o -path '*/mergecheck/ws/bots' -o -path '*/.cambc' -o -path '*/sdk' -o -path '*/cmake' \\) -prune -o -type f \\( -name '*.py' -o -name '*.sh' -o -name cambc.toml \\) -print 2>/dev/null"
  T=$(mktemp -d /data/zw4424/tmp/doctor_from.XXXXXX 2>/dev/null || mktemp -d)
  if timeout 600 ssh -o BatchMode=yes "$FROM" "$Q" | LC_ALL=C sort > "$T/there" && sh -c "$Q" | LC_ALL=C sort > "$T/here"; then
    LC_ALL=C comm -23 "$T/there" "$T/here" | sed 's#^/data/zw4424/##' > "$T/missing"
    n=$(wc -l < "$T/missing")
    if [ "$n" -eq 0 ]; then ok "no scripts or build workspaces on $FROM missing here"
    else fail "$n scripts/workspaces on $FROM missing here (list $T/missing; first: $(head -3 "$T/missing" | tr '\n' ' '))"
      echo "       copy: rsync -a --ignore-existing --files-from=$T/missing $FROM:/data/zw4424/ /data/zw4424/"; fi
  else warn "could not list /data/zw4424 on $FROM (ssh?)"; fi
fi
