#!/bin/sh
# platlock.sh CMD [ARGS...] - run one platform call (cambc matches download / summary ...) under a machine-wide lock,
# at least 3 s after any session's previous call: concurrent sessions queue instead of hitting 409 "Wait for your current
# download to finish" / 429 "Download queue is busy" (cambc-bc's wish, 26 Oct; platform-api-gentle). Exit 75 if the lock
# is not free within 15 min. The CMD's own exit code is returned.
# 10 Nov ~20:00Z (Builder, URGENT: nova_base_v708 was baked without v708's code; trunks on it would revert v708): while
# /data/zw4424/st/bq/SUBMIT_HOLD exists, every `submit` refuses (exit 75) and says why. rm the file to release.
case " $* " in *" submit "*)
  if [ -f /data/zw4424/st/bq/SUBMIT_HOLD ]; then echo "platlock: SUBMIT_HOLD present ($(head -1 /data/zw4424/st/bq/SUBMIT_HOLD)): submit refused" >&2; exit 75; fi ;;
esac
# 4 Nov (owner: our tools must not clog the account's requests while the owner views games on the website visualiser):
# replay DOWNLOADS keep at least PLAT_DL_GAP (15) s apart, and wait (without holding the lock, up to 2 h) while
# /data/zw4424/plat/PAUSE_DOWNLOADS is less than 2 h old: `touch` it before viewing, `rm` it after (it expires by itself).
case " $* " in *" download "*)
  P=/data/zw4424/plat/PAUSE_DOWNLOADS; w=0
  while [ -f "$P" ] && [ $(( $(date +%s) - $(stat -c %Y "$P" 2>/dev/null || echo 0) )) -lt 7200 ] && [ $w -lt 7200 ]; do sleep 30; w=$((w + 30)); done
  # 9 Nov 16:30Z (owner: critical games first; Coordinator: critgame made no triage pass for an hour, one download in five behind tvtfetch,
  # livepipe back-fills and the top-3 fetcher): critgame's downloads go first. While one waits, every other download holds back (at most
  # PLAT_HI_DEFER s, 300) before queueing on the lock, so the next free slot is critgame's.
  HID=/data/zw4424/plat/.dl_hi; mkdir -p "$HID" 2>/dev/null
  case "$(tr '\0' ' ' < /proc/$PPID/cmdline 2>/dev/null)" in
    *critgame.py*) : > "$HID/$$"; : > /data/zw4424/plat/.dl_pass; trap 'rm -f "${HID:?}/$$"' EXIT; trap 'exit 143' INT TERM ;;
    *) w=0
       while [ $w -lt "${PLAT_HI_DEFER:-60}" ]; do
         hi=0; for x in "$HID"/*; do [ -e "$x" ] || continue; if kill -0 "${x##*/}" 2>/dev/null; then hi=1; break; else rm -f -- "${x:?}"; fi; done
         [ $hi -eq 0 ] && break; sleep 5; w=$((w + 5))
       done
       # 9 Nov 21:00Z (Coordinator: live triage fell behind; critgame got 36 of 188 downloads in 30 min): while critgame's pass is active (it
       # downloaded in the last PLAT_PASS_S, 90 s: /data/zw4424/plat/.dl_pass), all other downloads TOGETHER keep PLAT_LO_GAP (15) s apart,
       # so critgame keeps most of the ~12/min and the others still get ~4/min
       PS=$(stat -c %Y /data/zw4424/plat/.dl_pass 2>/dev/null || echo 0); LO=/data/zw4424/plat/.platform.last_lo
       if [ $(( $(date +%s) - PS )) -lt "${PLAT_PASS_S:-0}" ]; then
         exec 8>>"$LO.lock"; flock -w 900 8
         l=$(cat "$LO" 2>/dev/null | tr -cd 0-9); l=${l:-0}
         d=$(( ${PLAT_LO_GAP:-15} - ($(date +%s) - l) )); [ $d -gt 0 ] && sleep $d
         date +%s > "$LO"; exec 8>&-
       fi ;;
  esac
  # 9 Nov ~17:05Z (owner: "Yes, test 8s and 5s", use the fastest gap that holds; replaces the 4 Nov 15 s rule): the default gap is read from
  # /data/zw4424/plat/dl_gap (one integer, s; 15 if missing), so the test can step it without editing this script; every download is logged
  GAP=${PLAT_DL_GAP:-$(cat /data/zw4424/plat/dl_gap 2>/dev/null | tr -cd 0-9)}; GAP=${GAP:-15}; DLLOG=1 ;;
*) GAP=3 ;;
esac
# NO ASSERTIONS LIVE (owner, 5 Nov: "make sure we never submit a bot with assertions"): a submit is refused when the bot dir
# is a check copy (name nova_chk_*) or its source holds any assertion, check or diag code: assert(, NOVA_CHECK, NOVA_ASSERT,
# fuel_pause/resume/adjust, or any host import a bot declares itself (import_module / import_name, e.g.
# b1235's diag dgr_pause; a real bot's imports all come from the SDK header, which is not in its src). Comment-only lines are
# ignored. Check copies live outside bots/ (tools/lab/chkbuild.py) and only ever play local test games.
# Test the guard without any platform call: sh tools/lab/platlock.sh --check-submit BOT_OR_DIR...  (exit 77 if one is refused)
guard_hit() {  # $1 = a bot dir with src/: prints the first offending line, if any
  grep -rnE '(^|[^_A-Za-z0-9])assert[[:space:]]*\(|NOVA_CHECK|NOVA_ASSERT|fuel_(pause|resume|adjust)|import_module|import_name|_pause_imp|_resume_imp' "$1/src" 2>/dev/null \
    | grep -v 'static_assert' | grep -vE '^[^:]*:[0-9]+:[[:space:]]*(//|\*|/\*)' | head -1
}
guard_args() {
  for a in "$@"; do
    case "$(basename -- "$a")" in nova_chk_*) echo "platlock: REFUSED: $a is an assertion check copy (nova_chk_*), never submitted" >&2; return 77 ;; esac
    for d in "$a" "bots/$a" "/homes/zw4424/cambc/bots/$a"; do   # a path, or a bot name relative to bots/
      [ -d "$d/src" ] || continue
      hit=$(guard_hit "$d")
      [ -n "$hit" ] && { echo "platlock: REFUSED: $d holds assertion/check/diag code ($hit); never submitted" >&2; return 77; }
    done
  done
  return 0
}
if [ "$1" = "--check-submit" ]; then
  shift; guard_args "$@"; rc=$?; [ $rc -eq 0 ] && echo "platlock: submit guard OK for: $*"; exit $rc
fi
case " $* " in *" submit "*) guard_args "$@" || exit 77 ;; esac
L=/data/zw4424/plat/.platform.lock
T=/data/zw4424/plat/.platform.last
# 8 Nov (owner: use the match quota to its full effect): match-groups calls don't touch the download queue the lock protects; waiting behind 15 s-apart downloads held
# them to about one a minute. Their own lane, same 3 s spacing. 9 Nov: `submissions list` too (every climb lane's version check queued behind
# 15 s-apart replay downloads, and they behind it); `matches show` too (critgame refile: 48 lookups queued behind downloads)
case " $* " in *" match-groups "*|*" matches list "*|*" matches show "*|*" ladder "*|*" submissions list "*) L=/data/zw4424/plat/.platform_groups.lock; T=/data/zw4424/plat/.platform_groups.last ;; esac  # 9 Nov: listings too (one page waited 64 s behind downloads)
exec 9>>"$L"
flock -w 900 9 || { echo "platlock: no lock within 15 min" >&2; exit 75; }
last=$(cat "$T" 2>/dev/null); now=$(date +%s)
case $last in ""|*[!0-9]*) last=0 ;; esac   # a missing or half-written stamp must not break every later call
[ $((now - last)) -lt "$GAP" ] && sleep $((GAP - (now - last)))
if [ -n "$DLLOG" ]; then  # download log: time, gap, seconds since the last call, exit code, 429 seen (the gap test reads /data/zw4424/plat/dl.log)
  E=/data/zw4424/plat/.dl_err.$$; t0=$(date +%s)
  "$@" 2> "$E"; rc=$?
  cat "$E" >&2; r429=$(grep -c -i -E "429|busy" "$E" 2>/dev/null); rm -f -- "${E:?}"
  echo "$(date -u +%FT%TZ) gap=$GAP since_last=$((t0 - last)) rc=$rc r429=${r429:-0} dur=$(( $(date +%s) - t0 ))" >> /data/zw4424/plat/dl.log
else
  "$@"; rc=$?
fi
date +%s > "$T"
exit $rc
