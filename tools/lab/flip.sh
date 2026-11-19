#!/bin/sh
# flip.sh TRUNK NEW "FLAG=VAL [FLAG=VAL ...]" - a trunk candidate that differs from TRUNK in runtime data flags only (1 Nov 2026).
# TRUNK holds every feature's code behind NULLSW/RSW data tables (`inline const volatile int X_TAB[] = { MAGIC, ... }`, see
# condor-work/reports/trunk_registry.md and trunk_protocol.md). This:
#   1. refuses any FLAG that is not `#define FLAG <int>` once, read only inside table initializers (tools/lab/flip.py check);
#   2. makes bots/NEW with newbot.sh (a real copy; no symlinks) and edits only those #define values;
#   3. predicts NEW's release wasm by patching the trunk's cached wasm at each table's slot-0 magic (seconds, no compile) and
#      checks it with wsec.py: code IDENTICAL, N data bytes. Trunk wasm cache: /data/zw4424/trunkproj/wasm/TRUNK-HASH.wasm
#      (built once per trunk source). NEW's predicted wasm: /data/zw4424/trunkproj/wasm/NEW-HASH.wasm;
#   4. writes bots/NEW/FLIP (TRUNK=, TRUNK_HASH=, FLIPS=, DATA_BYTES=) for shipcheck's TRUNK mode.
# FLIP_BUILD=1 also compiles NEW (~1 min) and requires the build to equal the predicted wasm byte for byte.
# Lab runs (abl.sh, condab.sh, shipcheck) compile NEW from its source as for any bot; the source is the truth.
REPO=/homes/zw4424/cambc; TP=/data/zw4424/trunkproj; CLI=/data/zw4424/cambc400/bin/cambc400; WSEC=/data/zw4424/rswproj/wsec.py
T=$1; N=$2; F=$3
[ -n "$T" ] && [ -n "$N" ] && [ -n "$F" ] || { echo 'usage: flip.sh TRUNK NEW "FLAG=VAL ..."'; exit 2; }
[ -d "$REPO/bots/$T/src" ] || { echo "flip.sh: no bot $T"; exit 1; }
python3 -I "$REPO/tools/lab/flip.py" check "$REPO/bots/$T/src" "$F" || { echo "flip.sh: refused"; exit 1; }
h() { python3 -I /homes/zw4424/cambc/tools/lab/srchash.py "$1"; }  # 3 Nov: one process, not six (exec audit fills /var/log/syslog); same hash
mkdir -p "$TP/wasm" "$TP/bots"
# trunk wasm, built once per trunk source (lock: two flips of one trunk build it once)
TH=$(h "$REPO/bots/$T"); TW=$TP/wasm/$T-$TH.wasm
exec 7> "$TP/wasm/.$T-$TH.lock"; flock 7
if [ ! -f "$TW" ]; then
  echo "flip.sh: building the trunk $T@$TH once (~1 min)"
  python3 -I "$REPO/tools/lab/pilotbuild.py" "$T" "$TW" > /dev/null 2>&1 ||
  rsync -a --delete --exclude .cambc --exclude build --exclude SHIPCHECK "$REPO/bots/$T/" "$TP/bots/$T/" &&
  (cd "$TP" && CMAKE_BUILD_PARALLEL_LEVEL=3 nice -n 10 "$CLI" build --release "bots/$T" > "$TP/wasm/$T-$TH.log" 2>&1) &&
  [ "$(h "$TP/bots/$T")" = "$TH" ] && cp "$TP/bots/$T/.cambc/build-release/bot-injected.wasm" "$TW.tmp" && mv "$TW.tmp" "$TW"
  [ -f "$TW" ] ||
  { echo "flip.sh: trunk build failed ($TP/wasm/$T-$TH.log)"; exit 1; }
fi
exec 7>&-
sh "$REPO/tools/lab/newbot.sh" "$T" "$N" || exit 1
D=$(readlink -f "$REPO/bots/$N")
[ -z "$(find "$D/" -type l)" ] || { echo "flip.sh: $D holds symlinks; stop"; exit 1; }
for kv in $F; do
  nm=${kv%%=*}; v=${kv#*=}
  fl=$(grep -l "^[[:space:]]*#[[:space:]]*define[[:space:]]\+$nm[[:space:]]" "$D"/src/*.h "$D"/src/*.cpp "$D"/src/*.cc 2>/dev/null)
  [ "$(echo "$fl" | wc -w)" = 1 ] || { echo "flip.sh: #define $nm found in: $fl"; exit 1; }
  sed -i "s/^\([[:space:]]*#[[:space:]]*define[[:space:]]\+$nm[[:space:]]\+\)-\?\(0[xX][0-9a-fA-F]\+\|[0-9]\+\)/\1$v/" "$fl"
done
NL=$(diff -r "$REPO/bots/$T/src" "$D/src" | grep -c '^>')
NF=$(for kv in $F; do echo "${kv%%=*}"; done | sort -u | wc -l)
[ "$NL" -le "$NF" ] || { echo "flip.sh: $NL source lines changed for $NF flags; stop"; exit 1; }
NH=$(h "$D"); NW=$TP/wasm/$N-$NH.wasm
python3 -I "$REPO/tools/lab/flip.py" patch "$REPO/bots/$T/src" "$D/src" "$TW" "$NW" || exit 1
WS=$(python3 -I "$WSEC" "$TW" "$NW" | grep -E '^(code|data) ')
echo "$WS"
echo "$WS" | grep -q '^code .*IDENTICAL' || { echo "flip.sh: wsec says the code differs; stop"; exit 1; }
DB=$(python3 -I "$REPO/tools/lab/flip.py" patch "$REPO/bots/$T/src" "$D/src" "$TW" /dev/null | sed -n 's/^data bytes changed: //p')
if [ "${FLIP_BUILD:-0}" = 1 ]; then
  rsync -a --delete --exclude .cambc --exclude build --exclude FLIP "$D/" "$TP/bots/$N/" &&
  (cd "$TP" && CMAKE_BUILD_PARALLEL_LEVEL=3 nice -n 10 "$CLI" build --release "bots/$N" > "$TP/wasm/$N-$NH.log" 2>&1) &&
  cmp "$TP/bots/$N/.cambc/build-release/bot-injected.wasm" "$NW" && echo "flip.sh: FLIP_BUILD: compiled wasm == predicted wasm" ||
  { echo "flip.sh: FLIP_BUILD: the compiled wasm differs from the prediction (or the build failed: $TP/wasm/$N-$NH.log)"; exit 1; }
fi
printf 'TRUNK=%s\nTRUNK_HASH=%s\nFLIPS=%s\nDATA_BYTES=%s\nWASM=%s\n' "$T" "$TH" "$F" "$DB" "$NW" > "$D/FLIP"
echo "flip.sh: bots/$N = $T + [$F]: code IDENTICAL, $DB data bytes (source $NH, predicted wasm $NW)"
