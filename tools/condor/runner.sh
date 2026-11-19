#!/bin/sh
# Condor job body: run the commands of one chunk file in parallel; print each command's output prefixed by its line id.
# sed -u writes one line per write(): with block buffering, outputs over 4 KB of parallel commands interleaved mid-line.
CHUNK=$1; PAR=${2:-12}
echo "## host $(hostname) cpus $(nproc) start $(date -u +%FT%TZ)"
while IFS="$(printf '\t')" read -r id cmd; do printf '%s\t%s\n' "$id" "$cmd"; done < "$CHUNK" |
  xargs -P "$PAR" -d '\n' -I{} sh -c 'id=$(printf "%s" "$1" | cut -f1); cmd=$(printf "%s" "$1" | cut -f2-); out=$(sh -c "$cmd" 2>&1); rc=$?; printf "%s\n" "$out" | sed -u "s/^/[$id] /"; echo "[$id] ## rc=$rc"' _ {}
echo "## end $(date -u +%FT%TZ)"
