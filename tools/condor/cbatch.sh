#!/bin/sh
# Run a file of shell commands (one per line) on the DoC HTCondor pool.
# Lines are split into jobs of CHUNK lines; each job runs its lines in parallel (PAR at a time) on one machine
# and writes ONE combined log (the home dir is NFS with a 60k-file quota, so keep per-command files out of it).
# usage: tools/condor/cbatch.sh CMDFILE OUTDIR [CHUNK] [PAR] [CPUS] [MEM_MB]
#   CBATCH_PRIO=N (optional): HTCondor job priority; it orders only our own queued jobs (higher first), never other users'.
#   OUTDIR must be on the shared home (e.g. /homes/zw4424/condor-runs/NAME); /data and /tmp are per machine.
#   Commands run with cwd = OUTDIR and must use absolute paths. Jobs can be suspended when a lab user is active.
# Watch: condor_q; results: OUTDIR/job_*.out (stdout of every command, prefixed by its line number).
set -e
export PATH=${CBATCH_CONDOR_BIN:-/usr/local/condor/release/bin}:$PATH   # selftest points this at a fake condor_submit
CMDS=$(readlink -f "$1"); OUT=$2; CHUNK=${3:-24}; PAR=${4:-12}; CPUS=${5:-$PAR}; MEM=${6:-8000}
mkdir -p "$OUT"; OUT=$(readlink -f "$OUT")
case "$OUT" in /homes/*|/vol/bitbucket/*) ;; *) echo "OUTDIR must be under /homes or /vol/bitbucket (shared with execute nodes)"; exit 1 ;; esac
# a reused OUTDIR would queue its old chunk_* files again (the queue matches chunk_*) and mix old job outputs with new
if ls "$OUT"/chunk_* > /dev/null 2>&1; then echo "OUTDIR $OUT already holds a batch (chunk_*): use a new OUTDIR"; exit 1; fi
cp "$(dirname "$(readlink -f "$0")")/runner.sh" "$OUT/runner.sh"; chmod +x "$OUT/runner.sh"
grep -v '^\s*$' "$CMDS" | grep -v '^\s*#' | awk '{print NR "\t" $0}' > "$OUT/all.tsv"
split -d -a 4 -l "$CHUNK" "$OUT/all.tsv" "$OUT/chunk_"
n=$(ls "$OUT"/chunk_* | wc -l)
cat > "$OUT/batch.sub" <<SUB
universe     = vanilla
executable   = $OUT/runner.sh
arguments    = \$(chunk) $PAR
initialdir   = $OUT
output       = $OUT/job_\$(chunk).out
error        = $OUT/job_\$(chunk).err
log          = $OUT/batch.log
request_cpus = $CPUS
request_memory = $MEM
$( [ -n "$CBATCH_PRIO" ] && echo "priority     = $CBATCH_PRIO" )
requirements = (OpSysAndVer == "Ubuntu26" || OpSysAndVer == "Ubuntu24" || OpSysAndVer == "Ubuntu22")
getenv       = True
should_transfer_files = NO
queue chunk matching files chunk_*
SUB
# the submit's own status must reach the caller: piped into tail it returned tail's 0, so on 27 Oct an expired Kerberos
# ticket looked like a queued batch and tourney.py waited 6 h on nothing
cd "$OUT"
if ! sub=$(condor_submit batch.sub 2>&1) || ! echo "$sub" | grep -q 'submitted to cluster'; then
  echo "$sub" | tail -5 >&2
  echo "condor_submit failed, nothing queued (Kerberos ticket expired? klist; only the owner renews it with kinit)" >&2
  exit 1
fi
echo "$sub" | tail -1
echo "$n jobs; outputs in $OUT"
