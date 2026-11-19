#!/bin/sh
# Condor job body of tools/lab/ubaudit.py's remote mode (UB_REMOTE=1; 30 Oct night, Tool builder: the instrumented debug
# build took ~10 min at -j3 and 40 mirror games ~6 min on the shared machine, at load 140). One job = one audit side:
# build one instrumented bot and play its mirror games on this node.
# usage: ubaudit_node.sh IN.tgz OUT.tgz FUEL LOGLIM JOBS
#   IN.tgz: proj/{cambc.toml,sdk,cmake,bots/NAME/src}, maps/*.map26a, botname, manifest.txt (paths written as @W@/...).
#   OUT.tgz: build.log, run.log, rc, rep/ID.repl26a, st/ID.json (the layout ubaudit.py's play_mirror reads), written to a temp
#   name and renamed when complete. Exit: 0 done, 3 bad input, 4 build failed (OUT.tgz still holds build.log).
IN=$1; OUT=$2; FUEL=$3; LOGLIM=$4; JOBS=${5:-8}
CLI=/homes/zw4424/condor-work/bin/cambc500   # byte-identical to /data/zw4424/cambc400/bin/cambc400 (checked 30 Oct)
export CAMBC_CACHE=/var/tmp/zw4424-cambc400-cache
. /homes/zw4424/cambc/tools/lab/cacheseed.sh  # 8 Nov: seed ninja/cmake/wasi-sdk from /homes (GitHub 504 broke node builds)
export CAMBC_WASMTIME_CACHE=/var/tmp/zw4424-wtcache
export CMAKE_BUILD_PARALLEL_LEVEL=$JOBS
W=/var/tmp/zw4424-ub-$$
mkdir -p "$W/out/rep" "$W/out/st" "$CAMBC_CACHE" "$CAMBC_WASMTIME_CACHE"
trap 'cd /; chmod -R u+w "$W" 2>/dev/null; rm -rf "$W"' EXIT
# node cleanup of killed jobs' dirs (owner 30 Oct: keep deleting what is not needed)
find /var/tmp -maxdepth 1 -user "$(id -u)" -type d -name 'zw4424-ub-*' ! -path "$W" -mmin +1440 -exec rm -rf {} + 2>/dev/null
finish() {
  echo "$1" > "$W/out/rc"
  tar -czf "$OUT.tmp.$$" -C "$W/out" . && mv -f "$OUT.tmp.$$" "$OUT"
  exit "$2"
}
tar -xzf "$IN" -C "$W" || finish 3 3
B=$(cat "$W/botname")
cd "$W/proj" || finish 3 3
t0=$(date +%s)
"$CLI" build "$W/proj/bots/$B" > "$W/out/build.log" 2>&1 || finish 4 4
echo "## build $(( $(date +%s) - t0 )) s on $(hostname) with -j$JOBS" >> "$W/out/build.log"
sed "s#@W@#$W#g" "$W/manifest.txt" > "$W/manifest.node.txt"
"$CLI" run-batch "$W/manifest.node.txt" --jobs "$JOBS" --fuel-quantum "$FUEL" --timeout 1800 --log-limit "$LOGLIM" \
  > "$W/out/run.log" 2>&1
finish $? 0
