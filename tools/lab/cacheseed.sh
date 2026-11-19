# cacheseed.sh - sourced by the *_node.sh scripts after `export CAMBC_CACHE=...` (8 Nov, Tool builder: GitHub returned 504 for
# ninja-linux.zip from ~09:09Z, and every CLI build on a node whose /tmp cache lacked ninja failed: puppet, diag, condab builds).
# Seeds each missing tool (ninja, cmake, wasi-sdk, assets) from one tar on /homes (nodes can't read /data), so a node build never
# fetches from the network. Each piece is unpacked into a temp dir and renamed into place under a lock: a concurrent build never
# sees a half-written tool. Re-make the seed after a CLI update (tool versions change):
#   cd /var/tmp/zw4424-cambc400-cache && tar -czf /homes/zw4424/condor-runs/toolcache/cambc400-cache.tgz ninja-* cmake-*-linux-x86_64 wasi-sdk-* assets
CACHESEED=/homes/zw4424/condor-runs/toolcache/cambc400-cache.tgz
if [ -n "$CAMBC_CACHE" ] && [ -s "$CACHESEED" ]; then
  mkdir -p "$CAMBC_CACHE" 2>/dev/null
  _need=""
  for _d in ninja-1.12.1-linux-x86_64 cmake-3.31.8-linux-x86_64 wasi-sdk-33 assets; do
    [ -d "$CAMBC_CACHE/$_d" ] || _need="$_need $_d"
  done
  if [ -n "$_need" ]; then
    (
      flock 9
      for _d in $_need; do
        [ -d "$CAMBC_CACHE/$_d" ] && continue
        _t="$CAMBC_CACHE/.seed.$$"
        rm -rf "$_t"; mkdir -p "$_t"
        tar -xzf "$CACHESEED" -C "$_t" "$_d" 2>/dev/null && mv "$_t/$_d" "$CAMBC_CACHE/$_d"
        rm -rf "$_t"
      done
    ) 9> "$CAMBC_CACHE.seed.lock"
  fi
  unset _need _d _t
fi
