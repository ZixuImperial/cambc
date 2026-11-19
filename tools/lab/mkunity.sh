#!/bin/sh
# mkunity.sh SRCDIR: turn a bot's src/ into a unity build (b1066). Every X.cpp is wrapped in #ifdef NOVA_UNITY_ALL;
# nova_all.cpp defines it and includes them all, undefining the .cpp-local macros between files.
# ORDER (7 Nov, Builder: rf5's ci.cpp uses combat.cpp's types; a regenerated alphabetical list put it first and two arms failed in
# trunkmerge with no text conflict): src/unity_order.txt (one .cpp a line), when present, gives the order; otherwise the order of
# the current nova_all.cpp is kept and files it does not list are added at the END (alphabetically among themselves). Files that
# no longer exist are dropped. A bot with no nova_all.cpp yet gets the alphabetical order, as before.
set -e
cd "$1"
# New layout (8 Nov refactor): only nova_all.cpp is a .cpp; it lists the .cc files in dependency order and has no guards. Keep that order, drop files
# that no longer exist, add unlisted .cc files at the end.
if [ -f nova_all.cpp ] && ! grep -q NOVA_UNITY_ALL nova_all.cpp; then
python3 -I -c '
import os, re
t = open("nova_all.cpp").read().split("\n")
listed = [m.group(1) for m in (re.match(r"#include \"([^\"]+\.cc)\"", x) for x in t) if m]
keep = [x for x in t if not (re.match(r"#include \"([^\"]+\.cc)\"", x) and not os.path.exists(re.match(r"#include \"([^\"]+\.cc)\"", x).group(1)))]
while keep and keep[-1] == "":
    keep.pop()
keep += ["#include \"%s\"" % f for f in sorted(os.listdir(".")) if f.endswith(".cc") and f not in listed]
open("nova_all.cpp.u", "w").write("\n".join(keep) + "\n")
os.replace("nova_all.cpp.u", "nova_all.cpp")
'
exit $?
fi
for f in *.cpp; do
  [ "$f" = nova_all.cpp ] && continue
  head -1 "$f" | grep -q '^#ifdef NOVA_UNITY_ALL' && continue
  { echo '#ifdef NOVA_UNITY_ALL // b1066 unity build: compiled only through nova_all.cpp'; cat "$f"; echo; echo '#endif // NOVA_UNITY_ALL'; } > "$f.u$$" && mv "$f.u$$" "$f"
done
order=$(python3 -I -c '
import os, re
cpps = sorted(f for f in os.listdir(".") if f.endswith(".cpp") and f != "nova_all.cpp")
if os.path.exists("unity_order.txt"):
    first = [x.strip() for x in open("unity_order.txt") if x.strip() and not x.startswith("#")]
elif os.path.exists("nova_all.cpp"):
    first = re.findall(r"^#include \"([^\"]+\.cpp)\"", open("nova_all.cpp").read(), re.M)
else:
    first = []
seen = []
for f in first + cpps:
    if f in cpps and f not in seen:
        seen.append(f)
print(" ".join(seen))
')
{
echo '// nova_all.cpp (b1066, fuel): unity build. Every other .cpp is empty when compiled alone (#ifdef NOVA_UNITY_ALL) and is'
echo '// compiled here as one translation unit, so -O3 inlines across files (the platform build has no LTO). Measured -1.1%'
echo '// fuel per turn, play identical. A NEW .cpp file needs no change: without the guard it still builds as its own unit.'
echo '// Macros a .cpp defines for itself are undefined after it, so they cannot leak into the next file.'
echo '// Order: src/unity_order.txt if present, else this file'"'"'s previous order with new files at the end (mkunity.sh).'
echo '#define NOVA_UNITY_ALL 1'
for f in $order; do
  echo "#include \"$f\""
  for m in $(grep -h -o -E '^\s*#\s*define\s+[A-Za-z_][A-Za-z0-9_]*' "$f" | awk '{print $NF}' | sed 's/^#define//' | sort -u); do
    [ "$m" = NOVA_UNITY_ALL ] || echo "#undef $m"
  done
done
} > nova_all.cpp.u$$
mv nova_all.cpp.u$$ nova_all.cpp
