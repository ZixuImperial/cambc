#!/bin/sh
# realbot.sh NAME - turn a bots/NAME link into a real folder on /homes: an armed candidate, like live and trunks, stays real
# (Builder 2 Nov, for the owner: test copies live on /data to save home files). mkmarker.py runs this before it writes a marker.
# Copies everything but the build caches, checks the source hash before touching the link, and keeps the /data original.
REPO=${NEWBOT_REPO:-/homes/USER/cambc}
N=$1; L=$REPO/bots/$N
[ -n "$N" ] || { echo "usage: realbot.sh NAME"; exit 1; }
case $N in .*|*[!A-Za-z0-9._+-]*) echo "realbot.sh: not a plain bot name: $N"; exit 1 ;; esac
[ -L "$L" ] || { [ -d "$L/src" ] && { echo "bots/$N is already real"; exit 0; }; echo "realbot.sh: no bot $N"; exit 1; }
R=$(readlink -f "$L") && [ -d "$R/src" ] || { echo "realbot.sh: bots/$N points at nothing"; exit 1; }
T=$REPO/bots/.real_$N.$$
h() { (cd "$1" && find src -type f | LC_ALL=C sort | xargs sha1sum | sha1sum | cut -c1-12); }
rsync -a --exclude .cambc --exclude build --exclude target "$R/" "$T/" || { rm -rf -- "${T:?}"; echo "realbot.sh: copy failed; link kept"; exit 1; }
HA=$(h "$R"); HB=$(h "$T")
[ "$HA" = "$HB" ] && [ -z "$(find "$T" -type l)" ] || { chmod -R u+w "$T"; rm -rf -- "${T:?}"; echo "realbot.sh: copy differs or holds links; link kept"; exit 1; }
rm -f -- "$L" && mv -T "$T" "$L" || { ln -s "$R" "$L"; chmod -R u+w "$T"; rm -rf -- "${T:?}"; echo "realbot.sh: swap failed; link restored"; exit 1; }
echo "bots/$N is now real (sources $HB; original kept at $R)"
