#!/bin/bash
# diskkeeper (13 Nov, Builder: keep /data >= 40 GB until midnight): every 15 min, when /data has < 45 GB free, prune (via rmdata.sh, which
# refuses in-use paths) finished panel dirs idle > 60 min (not a running check's tag, not a recent BANKWAIT), rdec_cache files untouched > 60 min,
# freshpool taken stubs > 12 h and smoke diag dirs > 6 h (never smoke/so). Stop: systemctl --user stop nova-diskkeeper
cd /homes/zw4424/cambc
L=/data/zw4424/st/bq/diskkeeper.list
while :; do
  f=$(df -BG /data | tail -1 | awk '{print $4}' | tr -d G)
  if [ "$f" -lt 45 ]; then
    run=$(pgrep -af '[s]hipcheck.py nova_' | awk '{print $5}' | tr '\n' '|')
    bw=$(grep 'BANKWAIT' /data/zw4424/st/bq/shipwatch.log | tail -50 | grep -o 'nova_b[0-9]*' | sed 's/nova_b//' | sort -u | tr '\n' '|')
    keep="${run}${bw}"; keep=${keep%|}; [ -n "$keep" ] || keep=NONE
    { find /data/zw4424/st/panel -maxdepth 1 -mindepth 1 -type d -mmin +60 ! -name 'shared_*' | grep -vE "/($keep)([^0-9]|$)"
      find /data/zw4424/rdec_cache -maxdepth 1 -type f -mmin +60 -amin +60
      find /data/zw4424/st/freshpool/taken -maxdepth 1 -mindepth 1 -mmin +720
      find /data/zw4424/st/smoke -maxdepth 1 -mindepth 1 -type d ! -name so -mmin +360
      # 13 Nov 16:2xZ (TB: /data fell to 30 GB; st/new/bots held 16 GB in 4,928 merged bots): bots untouched > 6 h, not a base/spar, not named
      # in armq.txt or pending_reads.txt (rmdata also refuses live/baseline, running and < 3 h bots)
      find /data/zw4424/st/new/bots -maxdepth 1 -mindepth 1 -mmin +190 | grep -vE 'nova_base_v|nova_spar_' \
        | grep -vFf <(grep -ohE 'nova_[A-Za-z0-9_]+' /data/zw4424/st/bq/armq.txt /data/zw4424/st/bq/pending_reads.txt 2>/dev/null | sort -u)
      # 13 Nov 18:1xZ (TB: trunk wasm + mergecheck caches ~3,500 files, autoclean's 6-24 h rule paused for load): cached builds idle > 2 h,
      # not of the live bot, a bot with a SHIPCHECK marker, or any running process's bot (rebuilt in ~1 min when needed)
      KB=$( { awk '{print $2}' /data/zw4424/st/bq/live.txt; ls /homes/zw4424/cambc/bots/*/SHIPCHECK 2>/dev/null | xargs -rn1 dirname | xargs -rn1 basename
              ps -u "$(id -u)" -o args= | grep -oE 'nova_[A-Za-z0-9_]+'; echo NONE_KEEP; } | sort -u)
      find /data/zw4424/trunkproj/wasm -maxdepth 1 -name '*.wasm' -mmin +120 | grep -vFf <(printf '%s\n' "$KB" | sed 's|^|/|; s|$|-|')
      find /data/zw4424/mergecheck/builds /data/zw4424/mergecheck/ws -mindepth 1 -maxdepth 2 -mmin +120 2>/dev/null | grep -vFf <(printf '%s\n' "$KB")
      # 13 Nov 18:0xZ (TB: 13 old live versions' shared fresh sets held ~4 GB): sets of versions other than the live one, idle > 2 h
      find /data/zw4424/st/sharedfresh -mindepth 1 -maxdepth 1 -mmin +120 ! -name "$(head -1 /data/zw4424/st/bq/live.txt | cut -d' ' -f1)"
      # 13 Nov 17:0xZ (TB: 16,777 collected condab batch dirs, ~11 GB; autoclean's 24 h rule is paused for load): collected batches idle > 3 h
      find /data/zw4424/condor_runs_archive -mindepth 1 -maxdepth 1 -name 'cq_*' -mmin +180 \
        | grep -vFf <(grep -ohE 'cq_[A-Za-z0-9_]+' /data/zw4424/st/bq/pending_reads.txt 2>/dev/null | sort -u; echo NONE_KEEP) ; } > $L 2>/dev/null
    n=$(wc -l < $L)
    [ "$n" -gt 0 ] && nice -n 19 sh tools/lab/rmdata.sh $L >> /data/zw4424/st/bq/diskkeeper.log 2>&1
    echo "$(date -u +%FT%TZ) free ${f}G, listed $n, now $(df -BG /data | tail -1 | awk '{print $4}')" >> /data/zw4424/st/bq/diskkeeper.log
  fi
  sleep 600
done
