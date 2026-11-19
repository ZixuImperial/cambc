#!/bin/sh
# detach.sh: run a long job or daemon in its own systemd user unit, so it survives VS Code / Claude session restarts (5 Nov, HOST:
# everything a Claude session starts, setsid included, sits in VS Code's app scope and dies with it).
# usage: sh tools/lab/detach.sh [-l LOGFILE] [-d DIR] [-n NICE] NAME CMD [ARGS...]
#   NAME   unit name suffix: the unit is nova-NAME (refused if one is already running; `systemctl --user stop nova-NAME` stops it)
#   -l     append stdout+stderr to LOGFILE (default /dev/null). Never the journal: journald forwards to syslog, which fills /var.
#   -d     working directory (default: the current one)   -n  nice level (default 10)
# The caller's PATH, HOME, KRB5CCNAME and every variable named CXE_* CONDAB_* OTF_* PILOT_* _CONDOR_* FP_* FS_* QG_* DP_* SC_* SP_* STRAT_* RAREBANK_* READ_* INFOREAD_* PMORA* (11 Nov: FS_* for flagscreen, b1860)
# ARM* LEAN_* BUGBAR* PARAMBAR* are passed through. Check: `systemctl --user status nova-NAME`; list: `systemctl --user list-units 'nova-*'`.
# Units stop when every login session of the user ends (Linger=no on DoC machines).
log=/dev/null; dir=$(pwd); nice=10
while [ $# -gt 0 ]; do
  case "$1" in
    -l) log=$2; shift 2 ;;
    -d) dir=$2; shift 2 ;;
    -n) nice=$2; shift 2 ;;
    *) break ;;
  esac
done
[ $# -ge 2 ] || { sed -n '2,12p' "$0"; exit 2; }
name=$1; shift
unit="nova-$name"
if systemctl --user is-active --quiet "$unit"; then echo "detach: $unit is already running (systemctl --user status $unit)" >&2; exit 3; fi
# 9 Nov 16:03Z: a crashed daemon's FAILED unit stays loaded (units started without --collect), and systemd-run then refuses the name
# ("already loaded"): healthwatch could not restart shipwatch for 14 min. Clear a failed or dead unit of this name first.
systemctl --user reset-failed "$unit" 2>/dev/null
case "$log" in /*) ;; *) log="$dir/$log" ;; esac
set -- -E PATH="$PATH" -E HOME="$HOME" ${KRB5CCNAME:+-E KRB5CCNAME="$KRB5CCNAME"} "$@"
envs=$(env | grep -E '^(CXE_|CONDAB_|OTF_|PILOT_|_CONDOR_|FP_|FS_|QG_|DP_|SC_|SP_|STRAT_|RAREBANK_|READ_|INFOREAD_|PMORA|ARM|LEAN_|BUGBAR|PARAMBAR)[A-Za-z0-9_]*=' | cut -d= -f1)
for v in $envs; do eval "val=\$$v"; set -- -E "$v=$val" "$@"; done
# KillMode=process: a job that detaches its own worker and returns (inforead, flagscreen run) keeps that worker; with the default
# control-group mode systemd killed every child the moment the main process exited (5 Nov: bk524's driver). So `systemctl stop` stops only the main process.
systemd-run --user --collect --quiet --unit="$unit" -p KillMode=process -p WorkingDirectory="$dir" -p Nice="$nice" \
  -p StandardOutput=append:"$log" -p StandardError=append:"$log" "$@" && exit 0
# 9 Nov 18:05Z: a STOPPED (inactive, not failed) unit started without --collect stays loaded, reset-failed doesn't clear it, and systemd-run
# refuses the name ("already loaded"; armq was down until started by hand). Start the loaded unit instead: same name, its own command.
if systemctl --user cat "$unit" >/dev/null 2>&1 && ! systemctl --user is-active --quiet "$unit"; then
  echo "detach: $unit is loaded but stopped: starting it (its recorded command)" >&2
  exec systemctl --user start "$unit"
fi
exit 1
