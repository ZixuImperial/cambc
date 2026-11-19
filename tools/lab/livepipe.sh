#!/bin/sh
# livepipe.sh --once | --loop [--every 600]  [--version vNNN] [--redo] [--no-fetch] [--jobs 4]
# Post-ship live pipeline (details: tools/lab/livepipe.py): when a new live version's unranked groups (unrsets.sh) have
# finished, fetch its unranked + ranked games into /data/zw4424/plat (unr_vNNN, rk_vNNN), run the standard detectors and
# write condor-work/reports/live/vNNN_digest.md + vNNN_summary.txt, one line in condor-work/reports/live/NEW_DIGESTS.log.
# Idempotent: a version already digested is skipped (state /data/zw4424/livepipe/state.json; --redo forces it).
# --loop: a pass every --every s (default 600), log /data/zw4424/livepipe/loop.log, PID in /data/zw4424/livepipe/loop.pid.
#   Start: setsid nohup sh tools/lab/livepipe.sh --loop --every 600 >> /data/zw4424/livepipe/loop.log 2>&1 < /dev/null &
#   Stop:  kill $(cat /data/zw4424/livepipe/loop.pid)   (SIGTERM: the running pass is abandoned cleanly, exit within ~1 min)
# Everything runs at nice 10 (livepipe.py nices itself; children inherit). Status: python3 -I tools/lab/livepipe.py status
cd /homes/zw4424/cambc || exit 2
mode=""; every=600; rest=""
while [ $# -gt 0 ]; do
  case $1 in
    --once) mode=once ;;
    --loop) mode=loop ;;
    --every) every=$2; shift ;;
    *) rest="$rest $1" ;;
  esac
  shift
done
[ -n "$mode" ] || { sed -n 2,10p "$0"; exit 2; }
case $every in ""|*[!0-9]*) echo "--every needs seconds"; exit 2 ;; esac
D=/data/zw4424/livepipe
mkdir -p $D
renice -n 10 -p $$ > /dev/null 2>&1
if [ $mode = once ]; then
  exec python3 -I tools/lab/livepipe.py once $rest
fi
if [ -s $D/loop.pid ] && kill -0 "$(cat $D/loop.pid)" 2>/dev/null; then
  echo "livepipe loop already running: pid $(cat $D/loop.pid)"; exit 1
fi
echo $$ > $D/loop.pid
child=""
stop() {
  echo "## livepipe loop stop (SIGTERM) $(date -u) pid $$"
  [ -n "$child" ] && kill -TERM "$child" 2>/dev/null && wait "$child" 2>/dev/null
  [ "$(cat $D/loop.pid 2>/dev/null)" = "$$" ] && rm -f $D/loop.pid
  exit 0
}
trap stop TERM INT HUP
echo "## livepipe loop start $(date -u) every ${every}s pid $$"
while :; do
  timeout -k 60 5400 python3 -I tools/lab/livepipe.py once $rest &
  child=$!; wait $child; child=""
  sleep "$every" &
  child=$!; wait $child; child=""
done
