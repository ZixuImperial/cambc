#!/bin/sh
# readernice (13 Nov, owner: "can you offload the readers"): every 30 s, analysts' local reader processes go to nice 19 so builds and
# shipchecks come first (big reads belong on the pilots: tools/lab/readmany.py). Matches python3 readers under the analysts' work dirs and the
# shared reader tools; never shipcheck/condab/stylepanel/armq/shipwatch/pilotd. Stop: systemctl --user stop nova-readernice
while :; do
  for p in $(pgrep -u zw4424 -f 'python3.*(/st/combat_py/|/st/deepan/|/st/pathf/|/st/aggr/|/st/prism/|/st/sharedmem/|/st/econ|condor-work/readers/|tools/lab/(replay|gamesum|deaths|mpairs|digest|lossclass|s21read|rvision)\.py|rd2\.py|lcp_agg|s21read)'); do
    case "$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null)" in *shipcheck*|*condab*|*stylepanel*|*armq*|*shipwatch*|*pilotd*|*readmany.py*) continue ;; esac
    [ "$(ps -o ni= -p $p 2>/dev/null | tr -d ' ')" = 19 ] || renice -n 19 -p $p >/dev/null 2>&1
  done
  sleep 30
done
