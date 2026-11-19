#!/bin/sh
# plat_fetch.sh ID|IDFILE... [--dest DIR] [--summary]: print each match's replay path, reusing a copy already on disk or
# downloading it once under platlock (usage and lookup order: tools/lab/plat_fetch.py).
exec nice -n 10 python3 -I "$(dirname "$0")/plat_fetch.py" "$@"
