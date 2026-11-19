#!/bin/sh
# rmdata.sh: the one way agents delete data we no longer need (owner 5 Nov: "just delete anything we do not need ... add it as a
# permission everywhere"). The allow rule covers only this script, so every deletion passes these checks:
#   - a path must be under /data/USER/ or /homes/USER/{condor-work,condor-runs}/ or /homes/USER/cambc/bots/ (no '..');
#   - never the pipeline's state files (st/bq/live.txt, best_model.txt, baseline.txt, armq.txt, pending_reads.txt, failure_chains.md),
#     the dirs st/bq and st/new/bots themselves, or the bots in live.txt's first 13 lines and baseline.txt;
#   - every deletion is logged (/data/USER/st/bq/rmdata.log on the host that deletes).
# usage: sh tools/lab/rmdata.sh [--dry] [--host HOST] LISTFILE      (one path per line; relative paths are under /data/USER)
#   --host HOST: run on HOST over ssh (LISTFILE must exist on HOST; /homes is shared, so this script is there too)
#   --dry: print what would go, delete nothing
dry=""; host=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry) dry=1; shift ;;
    --host) host=$2; shift 2 ;;
    *) break ;;
  esac
done
[ $# -eq 1 ] || { sed -n '2,11p' "$0"; exit 2; }
list=$1
if [ -n "$host" ]; then
  exec ssh -o BatchMode=yes "$host" sh /homes/USER/cambc/tools/lab/rmdata.sh ${dry:+--dry} "$list"
fi
[ -f "$list" ] || { echo "rmdata: no list $list on $(hostname)" >&2; exit 2; }
BQ=/data/USER/st/bq
# 8 Nov: the keep-list (/homes/USER/condor-work/keep_paths.txt, tools/lab/keeplist.py): kept paths, and folders holding one, are
# refused in ONE python pass before the loop (no process per path)
kfree=$(mktemp "${TMPDIR:-/tmp}/rmdata.free.XXXXXX"); kref=$(mktemp "${TMPDIR:-/tmp}/rmdata.kept.XXXXXX")
if python3 -I /homes/USER/cambc/tools/lab/keeplist.py --filter "$list" > "$kfree" 2> "$kref"; then
  cat "$kref" >&2; krefused=$(grep -c '^rmdata: refused' "$kref"); list=$kfree
else
  echo "rmdata: keep-list check failed: nothing deleted" >&2; rm -f "$kfree" "$kref"; exit 2
fi
protect=$( { head -13 $BQ/live.txt 2>/dev/null | awk '{print $2}'; head -3 $BQ/baseline.txt 2>/dev/null | tr ' ' '\n' | grep '^nova_'; } | sort -u)
log=$BQ/rmdata.log; [ -d $BQ ] || log=/dev/null
n=0; refused=${krefused:-0}; failed=0; absent=0
# Few process starts (5 Nov: one rm/grep/date per path made ~850k processes for 142k paths and filled /var with root's syslog):
# the checks are shell builtins, the removals go to ONE xargs rm per 2,000 paths, the log takes one time stamp per run.
stamp=$(date -u +%FT%TZ); hn=$(hostname); todo=$(mktemp "${TMPDIR:-/tmp}/rmdata.XXXXXX")
while IFS= read -r p; do
  [ -n "$p" ] || continue
  case "$p" in /*) ;; *) p="/data/USER/$p" ;; esac
  p=${p%/}
  case "$p" in *..*) echo "rmdata: refused (..): $p" >&2; refused=$((refused+1)); continue ;; esac
  case "$p" in
    /data/USER/?*|/homes/USER/condor-work/?*|/homes/USER/condor-runs/?*|/homes/USER/cambc/bots/?*) ;;
    *) echo "rmdata: refused (outside the data areas): $p" >&2; refused=$((refused+1)); continue ;;
  esac
  case "$p" in
    $BQ|$BQ/live.txt|$BQ/best_model.txt|$BQ/baseline.txt|$BQ/armq.txt|$BQ/pending_reads.txt|$BQ/failure_chains.md|/data/USER/st/new/bots|/data/USER/st/new)
      echo "rmdata: refused (pipeline state): $p" >&2; refused=$((refused+1)); continue ;;
  esac
  b=${p##*/}
  case "
$protect
" in *"
$b
"*) isprot=1 ;; *) isprot="" ;; esac
  if [ -n "$isprot" ]; then echo "rmdata: refused (live/baseline bot): $p" >&2; refused=$((refused+1)); continue; fi
  # 12 Nov (Planner: a reader's input dirs were deleted while it read them): a dir holding a .inuse file younger than 12 h, or any dir
  # above the path holding one, is in use by a reader: refused. Readers: `touch DIR/.inuse` while reading, rm it when done.
  q=$p; inuse=""
  while [ -n "$q" ] && [ "$q" != "/" ] && [ "$q" != "/data" ] && [ "$q" != "/homes" ]; do
    if [ -f "$q/.inuse" ] && [ -n "$(find "$q/.inuse" -mmin -720 2>/dev/null)" ]; then inuse=$q; break; fi
    q=${q%/*}
  done
  if [ -n "$inuse" ]; then echo "rmdata: refused (in use: $inuse/.inuse): $p" >&2; refused=$((refused+1)); continue; fi
  # 6 Nov: a missing path is counted (a relative path is read under /data/USER: bots/X there is not the repo's bots/X)
  if ! [ -e "$p" ] && ! [ -L "$p" ]; then echo "rmdata: absent (nothing there): $p" >&2; absent=$((absent+1)); continue; fi
  if [ -n "$dry" ]; then echo "would remove $p"
  else
    printf '%s\n' "$p" >> "$todo"
  fi
  n=$((n+1))
done < "$list"
if [ -z "$dry" ] && [ -s "$todo" ]; then
  tr '\n' '\0' < "$todo" | xargs -0 -n 2000 nice -n 19 rm -rf -- 2>/dev/null
  # check every path (builtins only) and log what went
  while IFS= read -r p; do
    if [ -e "$p" ] || [ -L "$p" ]; then echo "rmdata: could not remove (read-only?): $p" >&2; failed=$((failed+1)); n=$((n-1))
    else printf '%s %s %s\n' "$stamp" "$hn" "$p"; fi
  done < "$todo" >> "$log"
fi
rm -f "$todo" "$kfree" "$kref"
echo "rmdata on $(hostname): ${dry:+(dry) }$n removed, $refused refused, $failed failed, $absent absent"
