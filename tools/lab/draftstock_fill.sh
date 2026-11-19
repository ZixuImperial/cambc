#!/bin/sh
# draftstock_fill.sh: fill the draft map stock from the fresh pool (always leaving 8 ready sets for shipchecks) and keep lineups current for every draft key in use (owner 8 Nov).
# 9 Nov (Planner: filtered rare reads drew 31 of 420 maps): lineups now run every round, not only once the stock is full, for live AND every bot named in
# /data/zw4424/st/draftstock/want_bots.txt (one bot per line, '#' comments; a candidate whose draft code differs from live's, e.g. CIM2: add its bot name there).
# A lineups run derives only maps that lack them, so a round with nothing new costs one status pass. Target 48,000 ready maps.
# Stop: systemctl --user stop nova-draftstock-fill
cd /homes/zw4424/cambc || exit 1
DS="python3 -I tools/lab/draftstock.py"
WANT=/data/zw4424/st/draftstock/want_bots.txt
TARGET=${DS_TARGET:-48000}
while :; do
  have=$($DS status 2>/dev/null | awk '/^ready/{print $2; exit}' | tr -d ':')
  n=0
  while [ "${have:-0}" -lt "$TARGET" ] && [ $n -lt 4 ]; do
    ready=$(python3 -I tools/lab/freshpool.py --status 2>/dev/null | awk '/^ready/{print $2; exit}' | tr -d ':')
    [ "${ready:-0}" -gt 8 ] || break
    timeout 300 $DS fill --n 300 --wait 120
    n=$((n + 1)); have=$((have + 300))
  done
  live=$(head -1 /data/zw4424/st/bq/live.txt | cut -d' ' -f2)
  for b in $live $( [ -f "$WANT" ] && sed 's/#.*//' "$WANT" | tr -s ' \t' '\n' | grep -v '^$' ); do
    [ -d "bots/$b/src" ] || continue
    timeout 1800 $DS lineups --bot "$b" --par 6
  done
  [ $n -eq 0 ] && sleep 60
done
