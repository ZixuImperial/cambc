#!/usr/bin/env python3
"""mkmarker: write bots/BOT/SHIPCHECK only if shipwatch will accept it. Tool builder, 1 Nov (Builder: two markers bounced,
SUBJECT 63 > 60 chars, then TAG not the bot's number; 4 min lost).

usage: python3 -I tools/lab/mkmarker.py BOT [KEY=VAL ...] [--dry]
  TAG defaults to the bot's number (nova_b702s_self382 -> 702s); a given TAG must start with the bot's number digits.
  The marker is validated with shipwatch.py's own parse() (the same keys, LANE, SUBJECT format and length, NULLSW, BIG ...)
  on a temporary file first; nothing is written when it fails, and every error is printed. --dry validates and prints only.
  Values may contain spaces (SUBJECT="fix(econ): ...": quote the whole KEY=VAL for the shell).
Writes go to SHIPWATCH_REPO (default /homes/zw4424/cambc)/bots/BOT/SHIPCHECK, so a test can point at a fake repo.
Without --dry a bots/BOT link first becomes a real folder (realbot.sh): armed candidates, like live and trunks, stay real.
Only a session allowed to arm shipwatch should run this without --dry: writing the marker starts a check (and a submit
on PASS)."""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shipwatch  # noqa: E402


def main():
    a = sys.argv[1:]
    dry = "--dry" in a
    a = [x for x in a if x != "--dry"]
    if not a or "=" in a[0]:
        sys.exit(__doc__)
    bot, pairs = a[0], a[1:]
    errs = []
    kv = {}
    for p in pairs:
        if "=" not in p:
            errs.append(f"not KEY=VAL: {p!r}")
            continue
        k, v = p.split("=", 1)
        kv[k.strip()] = v.strip()
    num = re.match(r"nova_b(\d+)([a-z]*)", bot)
    if not num:
        errs.append(f"{bot}: shipwatch only takes nova_b<number>... bots (TAG comes from the number)")
    else:
        kv.setdefault("TAG", num.group(1) + num.group(2))
        if not re.fullmatch(rf"{num.group(1)}[a-z0-9_]*", kv["TAG"]):
            errs.append(f"TAG={kv['TAG']} does not belong to {bot}: it must be {num.group(1)} followed by [a-z0-9_]*")
    if "SUBJECT" in kv and len(kv["SUBJECT"].split(": ", 1)[-1]) > 60:
        errs.append(f"SUBJECT summary is {len(kv['SUBJECT'].split(': ', 1)[-1])} chars (max 60): {kv['SUBJECT']!r}")
    d = os.path.join(shipwatch.REPO, "bots", bot)
    if not os.path.isdir(os.path.join(d, "src")):
        errs.append(f"no {d}/src")
    if kv.get("TRUNK"):  # 2 Nov (TAG 1028): shipcheck's TRUNK mode refuses a copy with no FLIP; say so before it is armed
        try:
            m = re.search(r"^TRUNK=(\S+)", open(os.path.join(d, "FLIP")).read(), re.M)
            if not m or m.group(1) != kv["TRUNK"]:
                errs.append(f"{bot}/FLIP names trunk {m.group(1) if m else '(none)'}, not TRUNK={kv['TRUNK']}")
        except OSError:
            errs.append(f"TRUNK={kv['TRUNK']} needs a FLIP file: make the bot with flip.sh or fastship.py, not newbot.sh")
    text = "".join(f"{k}={v}\n" for k, v in kv.items())
    with tempfile.NamedTemporaryFile("w", suffix=".shipcheck", delete=False) as t:
        t.write(text)
    try:
        shipwatch.parse(t.name)
    except (ValueError, OSError) as e:
        errs.append(f"shipwatch.parse: {e}")
    finally:
        os.remove(t.name)
    print(text, end="")
    if errs:
        print("NOT WRITTEN:\n  " + "\n  ".join(errs))
        return 1
    if dry:
        print(f"OK (dry): {d}/SHIPCHECK not written")
        return 0
    if os.path.islink(d) and os.environ.get("REAL_ARM") == "1":  # 2 Nov: by default only a shipped bot becomes real (shipcheck.py); an armed one stays a link
        r = subprocess.run(["sh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "realbot.sh"), bot],
                           env=dict(os.environ, NEWBOT_REPO=shipwatch.REPO), capture_output=True, text=True)
        print((r.stdout + r.stderr).strip())
        if r.returncode or os.path.islink(d):
            print("NOT WRITTEN: could not make the bot a real folder")
            return 1
    p = os.path.join(d, "SHIPCHECK")
    with open(p + ".part", "w") as f:
        f.write(text)
    os.replace(p + ".part", p)
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
