#!/usr/bin/env python3
"""forceteam: a test copy of a bot that drafts a lineup we choose on every map, optionally in a shuffled pick order. Tool builder, 3 Nov
(owner: "play a team of our choice on every map, randomising the team order as well").

usage: python3 -I tools/lab/forceteam.py BASE NEW "Prism,Ryth,Vesper,Vendetta,Marcella" [--shuffle] [--seed N] [--no-build]
  BASE  any bot in bots/ (usually live: head -1 /data/zw4424/st/bq/live.txt).
  NEW   the copy's name; it must not start with nova_b (shipwatch only takes nova_b* bots, so a forced copy can never ship).
        Suggested: nova_ft_<lineup>, e.g. nova_ft_prryvvvema.
  The list holds 1-5 champions in priority order; on a map with team size T the first T are drafted (C&I is one pick, two bodies).
  A list shorter than T leaves the rest to the bot's own plan. Names: Ryth, Vesper (VV), Vendetta (Ve), CI (Cassi & Issac), Stellar,
  Prism, Marcella, Willow, Ren, Varg, Tavi, Heart (HoR); case and the short forms in draft.cpp's SHORT[] both work.
  --shuffle  the drafted T are picked in a random order, fixed per map (seeded by the map's walls and --seed), so it varies across maps
             and repeats in both seats of a map pair. Pick order is draft order, which breaks priority ties in turn order (rules brief).
  --seed N   0-8388607 (default 0): another shuffle per map.
  --no-build skip the pilot build check (it compiles the copy once, ~30 s, so a bad patch shows before games are queued).
Then play it like any bot: condab / cqbatch / gate legs against whatever opponent, e.g. on fresh maps from stratmaps.py.
How: newbot.sh copies BASE, and draft.cpp gets FTEAM_TAB plus a hook just before play_draft's try_pick, the same spot as
nova_spar_mite's SPAR_MITE core. Where Prism is not in the list, her carry plan is marked not viable (as in the Mite spar)."""
import os
import re
import subprocess
import sys

REPO = "/homes/zw4424/cambc"
LAB = REPO + "/tools/lab"
NAMES = {"ry": 0, "ryth": 0, "vv": 1, "vesper": 1, "ve": 2, "vendetta": 2, "ci": 3, "c&i": 3, "cassi": 3, "issac": 3, "st": 4, "stellar": 4,
         "pr": 5, "prism": 5, "ma": 6, "marcella": 6, "wi": 7, "willow": 7, "re": 8, "ren": 8, "va": 9, "varg": 9, "ta": 10, "tavi": 10,
         "hor": 11, "hr": 11, "heart": 11, "heart_of_ruin": 11, "heartofruin": 11}
SHORT = ["Ry", "VV", "Ve", "CI", "St", "Pr", "Ma", "Wi", "Re", "Va", "Ta", "HoR"]
MAGIC = "0x46544d31"
ANCHOR = "\tint picked = try_pick(choice, have) ? choice : -1;\n"
ANCHOR_V626 = "\tint picked = try_pick(d.choice, d.have) ? d.choice : -1;\n"  # refactored layout (v626 on): play_draft's state lives in a struct d
FUNC = """// FORCED TEAM (tools/lab/forceteam.py, owner 3 Nov): TEST COPIES ONLY, never a candidate. FTEAM_TAB[1]: up to 5 picks, 4 bits each
// (champion index + 1, first in the low bits); [2] bit 0 shuffles the pick order per map (seeded by the walls), bits 8+ a seed.
// The first team_size() listed are drafted; a shorter list leaves the rest to the plan.
inline const volatile int FTEAM_TAB[3] = { %s, %d, %d };
int ft_choice(std::uint16_t have, int choice)
{
	const int T = team_size();
	int L[5], n = 0;
	for (int i = 0, v = FTEAM_TAB[1]; i < 5 && n < T; ++i, v >>= 4)
		if ((v & 15) && (v & 15) <= NC)
			L[n++] = (v & 15) - 1;
	if (FTEAM_TAB[2] & 1)
	{
		std::uint32_t s = 2166136261u ^ static_cast<std::uint32_t>(FTEAM_TAB[2] >> 8);
		bbforeach(cambc::map::walls(), [&](vec2 p) { s = (s ^ static_cast<std::uint32_t>(p.x * 4099 + p.y)) * 16777619u; });
		for (int i = n - 1; i > 0; --i)
		{
			s = s * 1664525u + 1013904223u;
			const int j = static_cast<int>((s >> 16) %% static_cast<std::uint32_t>(i + 1));
			const int t = L[i];
			L[i] = L[j];
			L[j] = t;
		}
	}
	for (int i = 0; i < n; ++i)
		if (!(have >> L[i] & 1))
			return L[i];
	return choice;
}

"""
def die(m):
    sys.exit("forceteam: " + m)


def parse(a):
    if len(a) < 3 or a[0].startswith("-"):
        sys.exit(__doc__)
    base, new, lst = a[0], a[1], a[2]
    if new.startswith("nova_b"):
        die(f"{new}: a forced copy must not be named nova_b* (shipwatch would take it); use nova_ft_...")
    picks = []
    for x in re.split(r"[,\s]+", lst.strip()):
        if not x:
            continue
        c = NAMES.get(x.lower())
        if c is None:
            die(f"unknown champion {x!r}; one of {', '.join(SHORT)} or the full names")
        if c in picks:
            die(f"{x} twice: a team holds each champion once")
        picks.append(c)
    if not 1 <= len(picks) <= 5:
        die("give 1-5 champions")
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 0
    if not 0 <= seed < 1 << 23:
        die("--seed must be 0-8388607")
    return base, new, picks, "--shuffle" in a, seed, "--no-build" not in a


def main():
    base, new, picks, shuffle, seed, build = parse(sys.argv[1:])
    v = sum((c + 1) << (4 * i) for i, c in enumerate(picks))
    flags = (seed << 8) | int(shuffle)
    r = subprocess.run(["sh", f"{LAB}/newbot.sh", base, new], capture_output=True, text=True)
    if r.returncode:
        die(f"newbot.sh: {(r.stdout + r.stderr).strip()}")
    src = os.path.realpath(f"{REPO}/bots/{new}") + "/src"
    if subprocess.run(["find", src, "-type", "l"], capture_output=True, text=True).stdout.strip():
        die(f"{src} holds symlinks; not patching")
    p = src + ("/draft_turn.cc" if os.path.exists(src + "/draft_turn.cc") else "/draft.cpp")
    s = open(p).read()
    if "FTEAM_TAB" in s:
        die(f"{base} already carries FTEAM_TAB; copy a bot without it")
    # (anchors are checked below; a refusal leaves the new copy behind, named in the message)
    d_ = "d." if s.count(ANCHOR_V626) == 1 else ""
    anchor = ANCHOR_V626 if d_ else ANCHOR
    if s.count(anchor) != 1 or s.count("\nvoid play_draft()\n") != 1:
        die(f"{base}'s draft.cpp has no single try_pick anchor in play_draft; the patch needs updating for this bot")
    hook = ("\tif (FTEAM_TAB[1]) // FORCED TEAM (forceteam.py): test copies only\n"
            "\t{\n"
            f"\t\t{d_}choice = ft_choice({d_}have, {d_}choice);\n"
            + ("" if 5 in picks else "\t\tS.pz_viable = false; // Prism is not in the forced list\n")
            + "\t}\n")
    s = s.replace("\nvoid play_draft()\n", "\n" + FUNC % (MAGIC, v, flags) + "void play_draft()\n", 1)
    s = s.replace(anchor, hook + anchor, 1)
    open(p, "w").write(s)
    with open(os.path.realpath(f"{REPO}/bots/{new}") + "/FORCETEAM", "w") as f:
        f.write(f"BASE={base}\nPICKS={','.join(SHORT[c] for c in picks)}\nSHUFFLE={int(shuffle)}\nSEED={seed}\n")
    print(f"forceteam: bots/{new} = {base} drafting {', '.join(SHORT[c] for c in picks)}"
          f"{' (pick order shuffled per map, seed %d)' % seed if shuffle else ' (in that order)'}")
    if build:
        out = f"/data/zw4424/st/forceteam/{new}.wasm"
        os.makedirs(os.path.dirname(out), exist_ok=True)
        r = subprocess.run([sys.executable, "-I", f"{LAB}/pilotbuild.py", new, out], capture_output=True, text=True)
        if r.returncode or not os.path.exists(out):
            die(f"build check failed or no pilot answered: {(r.stdout + r.stderr).strip()[-400:]}\n"
                f"  build it locally from /data/zw4424/ablproj_4.0.0 to see the compiler error")
        print(f"forceteam: build OK ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
