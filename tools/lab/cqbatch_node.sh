#!/bin/sh
# Condor job body of tools/lab/cqbatch.py (30 Oct night, Tool builder): one slice of a run-batch manifest on this node.
# Condor's file transfer brings IN.tgz and the slice manifest into the job's scratch dir and takes OUT.tgz back.
# usage: cqbatch_node.sh IN.tgz OUT.tgz JOBS MANIFEST [run-batch options...]
#   IN.tgz: proj/{cambc.toml,sdk,cmake,bots/NAME/...}, maps/*. MANIFEST: run-batch lines with paths written as @W@/...
#   OUT.tgz: run.log, rc, out/GID.repl26a, out/GID.json.
IN=$1; OUT=$2; JOBS=$3; MAN=$4; shift 4
CLI=/homes/zw4424/condor-work/bin/cambc500   # byte-identical to /data/zw4424/cambc400/bin/cambc400
export CAMBC_CACHE=/var/tmp/zw4424-cambc400-cache
. /homes/zw4424/cambc/tools/lab/cacheseed.sh  # 8 Nov: seed ninja/cmake/wasi-sdk from /homes (GitHub 504 broke node builds)
export CAMBC_WASMTIME_CACHE=/var/tmp/zw4424-wtcache
export CMAKE_BUILD_PARALLEL_LEVEL=$JOBS
D=$(pwd)
W=/var/tmp/zw4424-cqb-$$
mkdir -p "$W/res/out" "$CAMBC_CACHE" "$CAMBC_WASMTIME_CACHE"
trap 'cd /; chmod -R u+w "$W" 2>/dev/null; rm -rf "$W"' EXIT
find /var/tmp -maxdepth 1 -user "$(id -u)" -type d -name 'zw4424-cqb-*' ! -path "$W" -mmin +1440 -exec rm -rf {} + 2>/dev/null
finish() {
  echo "$1" > "$W/res/rc"
  tar -czf "$D/$OUT" -C "$W/res" .
  exit 0
}
echo "## node $(hostname), $JOBS jobs" > "$W/res/run.log"
tar -xzf "$D/$IN" -C "$W" || finish 3
# 10 Nov (Tool Builder; owner: "speed up the overall pipeline"): every item used to compile its bots in a fresh /tmp dir (~35 s at -j8),
# though one pilot often runs 20+ items of the same bots. The project now lives in a per-node dir named by a hash of everything shipped
# (cambc.toml, sdk, cmake, bot sources): the first item builds there under a lock, later ones find the build up to date (ninja no-op).
# Same source -> same wasm: the games are unchanged. Maps stay in $W. CQB_NOCACHE=1: the old per-item build.
H=$(cd "$W/proj" && find . -type f ! -path '*/.cambc/*' -print0 | LC_ALL=C sort -z | xargs -0 sha1sum | sha1sum | cut -c1-16)
P=/var/tmp/zw4424-cqbproj-$H
if [ -z "$CQB_NOCACHE" ] && [ -n "$H" ]; then
  exec 9> "$P.lock"
  flock 9
  if [ ! -f "$P/.ready" ]; then
    rm -rf "$P"; mv "$W/proj" "$P" || finish 3
    echo "## cqbatch project cache: new $P (builds once on this node)" >> "$W/res/run.log"
  else
    echo "## cqbatch project cache: reusing $P (no rebuild)" >> "$W/res/run.log"
  fi
  touch "$P/.ready" "$P.lock"
  BMODE=; for a in "$@"; do [ "$a" = --release ] && BMODE=--release; done
  for b in "$P"/bots/*/; do  # build (or confirm up to date) under the lock, so parallel items never run ninja in one dir at once
    (cd "$P" && "$CLI" build "$b" $BMODE >> "$W/res/run.log" 2>&1) || { flock -u 9; finish 4; }
  done
  flock -u 9
  sed "s#@W@/proj#$P#g; s#@W@#$W#g" "$D/$MAN" > "$W/manifest.node.txt"
  cd "$P" || finish 3
else
  sed "s#@W@#$W#g" "$D/$MAN" > "$W/manifest.node.txt"
  cd "$W/proj" || finish 3
fi
find /var/tmp -maxdepth 1 -user "$(id -u)" -name 'zw4424-cqbproj-*' -mmin +720 ! -name "zw4424-cqbproj-$H*" -exec rm -rf {} + 2>/dev/null
"$CLI" run-batch "$W/manifest.node.txt" --jobs "$JOBS" "$@" >> "$W/res/run.log" 2>&1
finish $?
