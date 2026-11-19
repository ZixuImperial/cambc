#!/bin/sh
# Platform test set: create one unranked group per line of GROUPFILE ("<teamId> <label> <map1,...,map5>"),
# append them to arena/groups.txt under TAG, wait until all matches finish, then download every match's
# statistics into OUTDIR (plus OUTDIR/matches.txt: "<matchId> <map> <side> <result> <opponent>").
# Unranked groups play the CURRENT submission. Quota: 30 groups per rolling hour.
# usage: tools/lab/diag.sh GROUPFILE TAG OUTDIR [--zips]     (NODL=1: create and wait only, no downloads)
#        tools/lab/diag.sh --dl OUTDIR [--zips]               wait for an existing set, then download it
cd "$(dirname "$0")/../.." || exit 1
if [ "$1" = "--dl" ]; then GF=""; D=$2; ZIPS=$3; else GF=$1; TAG=$2; D=$3; ZIPS=$4; fi
mkdir -p "$D"
if [ -n "$GF" ]; then : > "$D/groups.txt"; echo "# $TAG $(date -u +%Y-%m-%dT%H:%MZ)" >> arena/groups.txt; fi
[ -n "$GF" ] && while read -r tid label maps; do
  [ -z "$tid" ] && continue
  out=$D/created_$label.json
  for try in 1 2 3 4 5 6 7 8 9 10; do
    timeout 120 /data/zw4424/cambc400/bin/cambc400 match-groups create "$tid" --maps "$maps" --json > "$out" 2> "$D/err_$label.txt" < /dev/null && break
    # quota (30 groups per rolling hour) or rate limit: wait as the server says, then retry
    wait_s=$(grep -o 'retry after [0-9]*' "$D/err_$label.txt" | grep -o '[0-9]*$')
    grep -qi "429" "$D/err_$label.txt" || break
    sleep $(( ${wait_s:-30} + 2 ))
  done
  gid=$(python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('groupId') or d.get('id') or '')" "$out" 2>/dev/null)
  if [ -n "$gid" ]; then echo "$gid ${TAG}_$label $TAG" >> arena/groups.txt; echo "$gid $label" >> "$D/groups.txt"; else echo "create failed: $label $(head -c 200 "$D/err_$label.txt")"; fi
done < "$GF"
# fetch ID KIND: one file under platlock, kept only when complete (a JSON that parses, a zip that tests). Every failure is
# retried (mostly transient: one replay zip in each of m23yP2, m25aP2 and m25bPN was lost to a single error, and later
# downloads of the same matches worked), so a download cut by the timeout is fetched again instead of being skipped.
# A 429 waits as long as the server says ("retry after 2 seconds"): the old fixed 62 s sleep cost 3-11 min a set (27 Oct).
fetch() {
  id=$1; kind=$2; out=$D/$id.$kind; tmp=$D/.part_$id.$kind; [ -s "$out" ] && return 0
  for i in 1 2 3 4 5 6 7 8 9 10; do
    rm -f "$tmp"
    if [ "$kind" = json ]; then sh /homes/zw4424/cambc/tools/lab/platlock.sh timeout 300 /data/zw4424/cambc400/bin/cambc400 matches summary "$id" --json -o "$tmp" > /dev/null 2> "$D/err.txt" < /dev/null &&
      python3 -I -c "import json, sys; json.load(open(sys.argv[1]))" "$tmp" 2>> "$D/err.txt" && mv "$tmp" "$out" && return 0
    else sh /homes/zw4424/cambc/tools/lab/platlock.sh timeout 300 /data/zw4424/cambc400/bin/cambc400 matches download "$id" -o "$tmp" > /dev/null 2> "$D/err.txt" < /dev/null &&
      unzip -tqq "$tmp" > /dev/null 2>> "$D/err.txt" && mv "$tmp" "$out" && { mkdir -p "$D/x_$id" && unzip -o -q "$out" -d "$D/x_$id"; return 0; }; fi
    rm -f "$tmp"
    echo "$id $kind try $i: $(head -c 300 "$D/err.txt" | tr '\n' ' ')" >> "$D/dl_errors.txt"
    if grep -qi "429\|rate" "$D/err.txt"; then
      ra=$(grep -o 'retry after [0-9]*' "$D/err.txt" | grep -o '[0-9]*$' | head -1)
      w=$(( ${ra:-60} + 1 )); [ $w -lt $((i * 3)) ] && w=$((i * 3)); sleep $w
    else sleep $((i * 5)); fi
  done
  return 1
}
# early ID: one try at a finished match's summary while the set still plays (itfast2, 28 Oct: the summaries came 4 min
# after the last replay). Kept only if it parses and names the outcome; anything else is left to the fetch after play.
early() {
  id=$1; out=$D/$id.json; tmp=$D/.part_$id.json; [ -s "$out" ] && return 0
  sh /homes/zw4424/cambc/tools/lab/platlock.sh timeout 300 /data/zw4424/cambc400/bin/cambc400 matches summary "$id" --json -o "$tmp" > /dev/null 2> "$D/err.txt" < /dev/null &&
    python3 -I -c "import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))['match']['outcome'] else 1)" "$tmp" 2>> "$D/err.txt" &&
    mv "$tmp" "$out" && return 0
  rm -f "$tmp"; return 1
}
# Replays (and, one try each, summaries) are fetched as their matches finish, while the rest of the set still plays (27 Oct: downloads took 20-40 min
# after play ended, 2-3x the play time); matches.txt is still written only once every match has finished.
while true; do
  pending=0; : > "$D/matches.tmp"
  while read -r gid label; do
    timeout 120 /data/zw4424/cambc400/bin/cambc400 match-groups show "$gid" --json > "$D/g_$gid.json" 2>/dev/null < /dev/null || { pending=1; continue; }
    python3 -I - "$D/g_$gid.json" >> "$D/matches.tmp" <<'PY' || pending=1
import json, sys
d = json.load(open(sys.argv[1])); bad = 0
for m in d["matches"]:
    if m["status"] != "finished":
        bad = 1; continue
    ME = "285f4eb5-e97f-4ea4-93c5-19e1590a1e5a"; me = [t for t in m["teams"] if t["teamId"] == ME][0]; op = [t for t in m["teams"] if t["teamId"] != ME][0]
    print(m["matchId"], m["map"], me["side"], me["result"], op["name"].replace(" ", "_"))
sys.exit(bad)
PY
  done < "$D/groups.txt"
  if [ "$NODL" != 1 ] && [ "$ZIPS" = "--zips" ]; then
    while read -r id map side res opp; do fetch "$id" zip; early "$id"; done < "$D/matches.tmp"
  fi
  [ $pending -eq 0 ] && break
  sleep 30
done
mv "$D/matches.tmp" "$D/matches.txt"
if [ "$NODL" = 1 ]; then echo "FINISHED $(wc -l < "$D/matches.txt") matches (not downloaded)"; exit 0; fi
# Replays first, so decset.sh can decode while the summaries download. The pre-registered checks read statistics too, so
# autoread.py waits for DONE (27 Oct: started at REPLAYS IN, v247n's check 2 read 16 of 50 games).
nmiss=0
if [ "$ZIPS" = "--zips" ]; then
  while read -r id map side res opp; do
    fetch "$id" zip || { nmiss=$((nmiss + 1)); echo "MISSING $id.zip ($map $res $opp)"; }
  done < "$D/matches.txt"
  echo "REPLAYS IN $(wc -l < "$D/matches.txt") matches (summaries next)"
fi
while read -r id map side res opp; do
  fetch "$id" json || { nmiss=$((nmiss + 1)); echo "MISSING $id.json ($map $res $opp)"; }
done < "$D/matches.txt"
echo "DONE $(wc -l < "$D/matches.txt") matches in $D$([ "$nmiss" -gt 0 ] && echo "; $nmiss files MISSING (rerun: tools/lab/diag.sh --dl $D [--zips])")"
