#!/bin/sh
# newbot.sh SRC NEW - make bots/NEW a real, writable copy of bots/SRC to edit (cambc-71, 27 Oct).
# Builder 2 Nov, for the owner: real folders on /homes cost ~59 home files each (78% of home growth at ~1,400 bots a day), so a new
# bot goes to /data/zw4424/st/new/bots with a bots/NEW link. A real folder in bots/ only with REAL=1; shipping
# makes a bot real (shipcheck.py -> realbot.sh). This copies the resolved directory's src/ (and compile_commands.json, never
# the .cambc / build caches), makes it writable (live builds' src/ is read-only) and prints both source hashes (equal until you
# edit NEW). Refuses a real folder at NEWBOT_MAX_FILES home files (default 56,000; condab's preflight is 57,000).
# Refuses an existing bots/NEW or a name used under /data. Never copies SHIPCHECK, SHIPCHECK.* or FLIP (1 Nov: a copy of v385 inherited its FLIP
# and would have run in TRUNK mode; flip.sh writes its own FLIP after the copy).
REPO=${NEWBOT_REPO:-/homes/zw4424/cambc}
SRC=$1; NEW=$2; OLD=${NEWBOT_STORE:-/data/zw4424/st/new/bots}
[ -n "$NEW" ] && [ -z "$3" ] || { echo "usage: newbot.sh SRC NEW"; exit 1; }
case $NEW in .*|*[!A-Za-z0-9._+-]*) echo "newbot.sh: NEW must be a plain bot name: $NEW"; exit 1 ;; esac
# 9 Nov (Tool Builder): the live bot carries its shipped switch unbaked; armq merges onto trunks built on the baked base (bq/diffbase.txt), so
# a donor copied from the live dir conflicted wherever its edit sat next to a baked line (b1777 GNC v v651 HVY_TAB). When SRC is the live
# bot named in diffbase.txt with identity ok, copy that base instead (play-identical, 40/40). NEWBOT_UNBAKED=1 keeps SRC.
DB=$(head -1 /data/zw4424/st/bq/diffbase.txt 2>/dev/null)
case "$DB" in "$SRC "*"identity ok"*) B=$(echo "$DB" | cut -d" " -f2)
  if [ -z "$NEWBOT_UNBAKED" ] && [ -d "$REPO/bots/$B/src" ]; then echo "newbot.sh: $SRC is live; copying its baked base $B (bq/diffbase.txt) so armq merges cleanly (NEWBOT_UNBAKED=1 to keep $SRC) -> arm it as $NEW:$B"; SRC=$B; fi ;;
esac
R=$(readlink -f "$REPO/bots/$SRC") && [ -d "$R/src" ] || { echo "newbot.sh: no bot $SRC"; exit 1; }
[ -e "$REPO/bots/$NEW" ] || [ -L "$REPO/bots/$NEW" ] && { echo "newbot.sh: bots/$NEW exists ($(readlink -f "$REPO/bots/$NEW")); pick another name"; exit 1; }
[ -e "$OLD/$NEW" ] && { echo "newbot.sh: $OLD/$NEW exists; pick another name"; exit 1; }
# 2 Nov: trunks too go to /data: armq merges several an hour. Only a shipped bot becomes real (shipcheck.py -> realbot.sh).
if [ -n "$REAL" ]; then
  F=$(python3 -I "$REPO/tools/lab/homequota.py" 2>/dev/null | tail -1 | cut -d' ' -f1)
  [ "${F:-0}" -ge "${NEWBOT_MAX_FILES:-56000}" ] && { echo "newbot.sh: home holds $F files (limit ${NEWBOT_MAX_FILES:-56000}); remove old bots first"; exit 1; }
  D=$REPO/bots/$NEW; T=$REPO/bots/.new_$NEW.$$
else
  mkdir -p "$OLD"; D=$OLD/$NEW; T=$OLD/.new_$NEW.$$
fi
rsync -a --exclude .cambc --exclude build --exclude SHIPCHECK --exclude "SHIPCHECK.*" --exclude FLIP "$R/" "$T/" && chmod -R u+w "$T" && mv -T "$T" "$D" || { rm -rf -- "${T:?}"; exit 1; }
[ -n "$REAL" ] || ln -s "$D" "$REPO/bots/$NEW" || exit 1
# 10 Nov (Rule Checker C41: STRIPPED's SOURCE= names the live the BASE was baked from, and was read as the candidate's build base): the copy
# records what it was made from; a later rebase or trunk build is not reflected in either file, so judge a candidate's base by content (base_check)
printf 'BASE=%s\nWHEN=%s\nNOTE=newbot copy source; STRIPPED SOURCE= is the live this base was baked from\n' "$(basename "$R")" "$(date -u +%FT%TZ)" > "$D/BASE"
h() { python3 -I /homes/zw4424/cambc/tools/lab/srchash.py "$1"; }  # 3 Nov: one process, not six (exec audit fills /var/log/syslog); same hash
echo "bots/$NEW${REAL:+ (real)} -> $D (copy of $R; sources $(h "$R") = $(h "$D")); edit $D/src, never $R"
