#!/bin/sh
# Condor job body of tools/lab/mergecheck.py (01 Nov): release-build bots on a node and send back bot-injected.wasm.
# usage: mergecheck_node.sh IN.tgz OUT.tgz JOBS BOT...   IN.tgz: proj/{cambc.toml,sdk,cmake,bots/BOT/src}; OUT.tgz: BOT.wasm, BOT.log
IN=$1; OUT=$2; JOBS=$3; shift 3
CLI=/homes/zw4424/condor-work/bin/cambc500   # byte-identical to /data/zw4424/cambc400/bin/cambc400 (cqbatch_node.sh)
export CAMBC_CACHE=/var/tmp/zw4424-cambc400-cache
. /homes/zw4424/cambc/tools/lab/cacheseed.sh  # 8 Nov: seed ninja/cmake/wasi-sdk from /homes (GitHub 504 broke node builds)
export CMAKE_BUILD_PARALLEL_LEVEL=$JOBS
D=$(pwd)
W=/var/tmp/zw4424-mcb-$$
mkdir -p "$W/res" "$CAMBC_CACHE"
trap 'cd /; chmod -R u+w "$W" 2>/dev/null; rm -rf "$W"' EXIT
echo "node $(hostname)" > "$W/res/node.log"
tar -xzf "$D/$IN" -C "$W" || { tar -czf "$D/$OUT" -C "$W/res" .; exit 0; }
cd "$W/proj" || exit 0
for b in "$@"; do
  if [ "$MCB_DEBUG" = 1 ]; then  # 7 Nov: debug builds for dbgso (diag copies) off this machine
    # 11 Nov (Builder/b1844: a source that did not compile came back "built"): a stale wasm in the packed tree was copied after a failed
    # build. The old wasm goes first, and only a zero exit sends one back (the log always goes back)
    rm -f "bots/$b/.cambc/build/bot-injected.wasm"
    "$CLI" build "bots/$b" > "$W/res/$b.log" 2>&1 && cp "bots/$b/.cambc/build/bot-injected.wasm" "$W/res/$b.wasm" 2>/dev/null
  else
    rm -f "bots/$b/.cambc/build-release/bot-injected.wasm"
    "$CLI" build --release "bots/$b" > "$W/res/$b.log" 2>&1 && cp "bots/$b/.cambc/build-release/bot-injected.wasm" "$W/res/$b.wasm" 2>/dev/null
  fi
done
tar -czf "$D/$OUT" -C "$W/res" .
exit 0
