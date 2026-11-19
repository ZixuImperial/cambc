#!/usr/bin/env python3
"""rulestest: the bot's rule helpers (rs::, mu::) against the Rule checker's expected-value tables (Tool builder, 6 Nov; owner: "make sure
our numbers are correct and consistent throughout the code base"). Tables: condor-work/reports/rulestables/*.csv (every row cites
GameRules.md; timing rows engine-checked on 3.0.0).

The helpers read real engine constants through the SDK (cambc::constants, emblem magnitudes), so they run where those exist: in cxe. A test
copy of BOT (newbot.sh, never shippable: it imports env.cxe_probe, which platlock's submit guard refuses) evaluates every row once on its
first play turn and reports each value with cxe_probe; one cxe game; then the values are compared with the tables.

usage: python3 -I tools/lab/rulestest.py BOT [--base BASE] [--keep]   -> exit 0 PASS, 1 FAIL (a direct-helper row differs), 2 could not run
  --base BASE: skip (exit 0, "unchanged") when BOT's rs.h / mult.h equal BASE's and the tables are unchanged since BASE was last tested
Rows:
  FAIL rows (one helper call): tribute rs::tribute_turns / rs::tribute_rounds; recall rs::recall_rounds; capture rs::capture_pay (holder
       from the start or none); champion respawn rs::champ_respawn_rounds (death before its own turn); kill gold rs::kill_gold;
       damage multipliers mu::rule(att, vs, OUT) x mu::hor x mu::rule(tgt, vs, IN) when the bot has mult.h (b1347)
  WARN rows (a composition of helpers, not one call): capture with a holder joining mid-capture (1 + (j - 1) + capture_rounds(5 - (j - 1), true));
       rs::capture_join_pay(j) is its FAIL row where the bot has it (bh66)
Output: /data/USER/st/rulestest/<bot>_<stamp>/report.txt (every mismatch with its table, row and GameRules source) and rows.tsv."""
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
TABLES = "/homes/USER/condor-work/reports/rulestables"
OUT = "/data/USER/st/rulestest"
sys.path.insert(0, f"{REPO}/tools/cxe")
FAMS = dict(skirmish=11, collectors=13, monster=0, durability=2, jungle=4, treasure=3, hunter=10)
FILLER = [5, 7, 8, 1, 6, 9, 12]  # families that change no damage multiplier (Collectors counts every family held)


def rows(name):
    return list(csv.DictReader(open(f"{TABLES}/{name}")))


F_ALL = (1 << 14) - 1
F_GREED = 12  # GameRules.md:317
M = "nova::mu::"
REN, SK, COL, DUR = "rs::ren_ret(100.0f)", 1 << 11, 1 << 13, 1 << 2
EXT = {
    "mu::rule(Collectors+Greed, CHAMP, OUT)": [f"{M}rule({(1 << 13) | (1 << F_GREED)}u, {M}CHAMP, {M}OUT)"],
    "mu::rule(Greed, CHAMP, OUT)": [f"{M}rule({1 << F_GREED}u, {M}CHAMP, {M}OUT)"],
    "mu::rule(all 14 families, CHAMP, OUT)": [f"{M}rule({F_ALL}u, {M}CHAMP, {M}OUT)"],
    "mu::rule(all 14 families, CAMP, OUT)": [f"{M}rule({F_ALL}u, {M}CAMP, {M}OUT)"],
    "mu::rule(Jungle, CHAMP, IN)": [f"{M}rule({1 << 4}u, {M}CHAMP, {M}IN)"],
    "mu::hor(1000, 1500)": [f"{M}hor(1000.0f, 1500.0f)"],
    "mu::hor(750, 1500)": [f"{M}hor(750.0f, 1500.0f)"],
    "mu::hor(0, 1000)": [f"{M}hor(0.0f, 1000.0f)"],
    "mu::code_of(Dur / Skirmish / Collectors alone / Sk+Col / all)": [f"{M}code_of({x}u)" for x in (1 << 2, 1 << 11, 1 << 13, (1 << 11) | (1 << 13), F_ALL)],
    "pair[Sk+Col(2)][Dur]": [f"{M}MU_CODE.pair[{M}code_of({(1 << 11) | (1 << 13)}u)][1]"],
    "rs::camp_out_mult(Monster)": ["rs::camp_out_mult(1u)"],
    "rs::camp_out_mult(Collectors)": [f"rs::camp_out_mult({1 << 13}u)"],
    "rs::camp_out_mult(Monster + Collectors)": [f"rs::camp_out_mult({1 | (1 << 13)}u)"],
    "rs::camp_out_mult(Monster + Skirmish + Collectors)": [f"rs::camp_out_mult({1 | (1 << 11) | (1 << 13)}u)"],
    "rs::ren_ret(100) / (0)": ["rs::ren_ret(100.0f)", "rs::ren_ret(0.0f)"],
    "rs::gold_mult none / Treasure / Vesper / both": ["rs::gold_mult(0u, false)", "rs::gold_mult(8u, false)", "rs::gold_mult(0u, true)", "rs::gold_mult(8u, true)"],
    "rs::tribute_rounds(0, any)": ["rs::tribute_rounds(0, false)"],
    "rs::capture_rounds(2, holder) / (5, holder) / (3, no holder)": ["rs::capture_rounds(2, true)", "rs::capture_rounds(5, true)", "rs::capture_rounds(3, false)"],
    "rs::slot_cooldown / crystal_rounds / lock_range": ["rs::slot_cooldown()", "rs::crystal_rounds()", "rs::lock_range()"],
    # b1396: the Ren, split and Prospector rows that are a product of helpers. None = no helper for that part (shield_turns), not tested.
    "Ren retaliation plain, F 100": [REN],
    "Ren retaliation, Ren Skirmish": [f"{REN} * {M}rule({SK}u, {M}CHAMP, {M}OUT)"],
    "Ren retaliation, Ren Collectors (1 family)": [f"{REN} * {M}rule({COL}u, {M}CHAMP, {M}OUT)"],
    "Ren retaliation, attacker Durability": [f"{REN} * {M}rule({DUR}u, {M}CHAMP, {M}IN)"],
    "Ren retaliation, Ren Skirmish v attacker Durability": [f"{REN} * {M}rule({SK}u, {M}CHAMP, {M}OUT) * {M}rule({DUR}u, {M}CHAMP, {M}IN)"],
    "Ren retaliation v camp, Monster": [f"{REN} * rs::camp_out_mult(1u)"],
    "Ren retaliation v camp, Collectors (1 family)": [f"{REN} * rs::camp_out_mult({COL}u)"],
    "Ren retaliation v camp, Monster + Collectors (2 families)": [f"{REN} * rs::camp_out_mult({1 | COL}u)"],
    "Ren retaliation v camp, Skirmish": [f"{REN} * rs::camp_out_mult({SK}u)"],
    "split 21 among 2, lowest ID / other": ["rs::split_share(21, 2, true)", "rs::split_share(21, 2, false)"],
    "split 60 among 3 / 21 among 3": ["rs::split_share(60, 3, false)", "rs::split_share(21, 3, false)"],
    "split 14 gems among 3, lowest ID / others": ["rs::split_share(14, 3, true)", "rs::split_share(14, 3, false)"],
    "split 20 gold among 3, lowest ID / others": ["rs::split_share(20, 3, true)", "rs::split_share(20, 3, false)"],
    "Prospector solo: 1 gem cluster / 2 clusters": ["rs::gem_cluster_gems() + rs::prospector_bonus(rs::gem_cluster_gems())", "2 * rs::gem_cluster_gems() + rs::prospector_bonus(2 * rs::gem_cluster_gems())"],
    "Prospector shared by two, holder": ["rs::split_share(2 * rs::gem_cluster_gems(), 2, false) + rs::prospector_bonus(rs::split_share(2 * rs::gem_cluster_gems(), 2, false))"],
    "rs::durability_mult / jungle / shield_turns": ["rs::durability_mult()", f"{M}rule({1 << 4}u, {M}CAMP, {M}IN)", None],
}


def build_cases():
    """-> [(kind, row index, C++ expression, expected value, scale, label, severity, source)]"""
    cs = []
    for i, r in enumerate(rows("tribute.csv")):
        g, e = int(r["gems_at_start"]), r["tribute_emblem"] == "1"
        src = r.get("source", "")
        cs.append((1, i, f"rs::tribute_turns({g}, {str(e).lower()})", int(r["turn_ends"]), 1, f"tribute_turns({g}, {e})", "FAIL", src))
        cs.append((2, i, f"rs::tribute_rounds({g}, {str(e).lower()})", int(r["rounds_start_to_completion"]), 1, f"tribute_rounds({g}, {e})", "FAIL", src))
    for i, r in enumerate(rows("recall.csv")):
        h, p = r["home_emblem"] == "1", r["prefired_last_turn"] == "1"
        cs.append((3, i, f"rs::recall_rounds({str(h).lower()}, {str(p).lower()})", int(r["rounds_from_decision_turn_to_arrival"]), 1,
                   f"recall_rounds(home={h}, prefired={p})", "FAIL", r.get("source", "")))
    for i, r in enumerate(rows("capture.csv")):
        exp = int(r["paid_at_round_start_offset (formula min(6, max(4, join+3)))"])
        j = r["holder_join_offset"]
        if r["case"].startswith("no holder"):
            cs.append((4, i, "rs::capture_pay(false)", exp, 1, "capture_pay(no holder)", "FAIL", r["source"]))
        elif j == "0":
            cs.append((4, i, "rs::capture_pay(true)", exp, 1, f"capture_pay(holder) [{r['case']}]", "FAIL", r["source"]))
        elif j.isdigit():
            # bh66 (6 Nov): j counts from the step-on round R, the timer starts at R + 1, so j - 1 timer rounds ran before the join
            cs.append((5, i, f"1 + ({j} - 1) + rs::capture_rounds(rs::rules().capture_time - ({j} - 1), true)", exp, 1,
                       f"capture, holder joins at +{j} [{r['case']}]", "WARN", r["source"]))
            cs.append((4, i, f"rs::capture_join_pay({j})", exp, 1, f"capture_join_pay({j}) [{r['case']}]", "FAIL", r["source"]))
    for i, r in enumerate(rows("champion_respawn.csv")):
        if "before" in r["case"]:
            cs.append((6, i, "rs::champ_respawn_rounds()", int(r["alive_at_own_turn_round_D_plus"]), 1, "champ_respawn_rounds()", "FAIL", r["source"]))
    with open(f"{TABLES}/gold_bonus.csv") as gf:  # two columns named source: DictReader kept the last, so `kill` never matched and these rows never ran (b1394)
        gr = csv.reader(gf)
        gh = next(gr)
        gh[0] = "income"
        gold = [dict(zip(gh, x)) for x in gr]
    for i, r in enumerate(gold):
        if r["income"] != "kill":
            continue
        fam = (1 << FAMS["treasure"] if r["treasure"] == "1" else 0) | (1 << FAMS["hunter"] if r["hunter"] == "1" else 0)
        vv = "true" if r["vesper"] == "1" else "false"
        cs.append((7, i, f"rs::kill_gold({fam}, {vv})", int(r["gold_displayed_floor"]), 1,
                   f"kill_gold(treasure={r['treasure']}, hunter={r['hunter']}, vesper={r['vesper']})", "FAIL", r["source"]))
    for i, r in enumerate(rows("damage_mult.csv")):
        vs = "nova::mu::CAMP" if r["target"] == "camp" else "nova::mu::CHAMP"  # dealt: against the target's kind
        vsi = "nova::mu::CAMP" if r["attacker"] == "camp" else "nova::mu::CHAMP"  # taken: from the attacker's kind
        att = 0
        if r["att_skirmish"] == "1":
            att |= 1 << FAMS["skirmish"]
        if r["att_monster"] == "1":
            att |= 1 << FAMS["monster"]
        k = int(r["att_collectors_families(0=no Collectors)"])
        if k:
            att |= 1 << FAMS["collectors"]
            for f in FILLER:
                if bin(att).count("1") >= k:
                    break
                att |= 1 << f
            if bin(att).count("1") != k:
                continue  # the row names fewer families than its other emblems: not a consistent row
        tgt = (1 << FAMS["durability"] if r["tgt_durability"] == "1" else 0) | (1 << FAMS["jungle"] if r["tgt_jungle"] == "1" else 0)
        miss = float(r["att_HoR_missing_hp_fraction"])
        expr = (f"nova::mu::rule({att}u, {vs}, nova::mu::OUT) * nova::mu::hor({1.0 - miss:.6f}f, 1.0f) * nova::mu::rule({tgt}u, {vsi}, nova::mu::IN)")
        cs.append((8, i, expr, float(r["multiplier"]), 10000, f"mult {r['attacker']}->{r['target']} skirm={r['att_skirmish']} coll={k} "
                   f"mon={r['att_monster']} hor_miss={miss} dur={r['tgt_durability']} jng={r['tgt_jungle']}", "FAIL", r["source"]))
    # extended_rows.csv (b1394): the rows that are one helper call. Label -> one expression per " / " part of `expected`; the other rows
    # (splits, turn order, Ren in play, Prospector) need a game or a body, not a helper, and stay unwired.
    n = 0
    for r in rows("extended_rows.csv"):
        ex = EXT.get(r["helper_or_case"])
        if not ex:
            continue
        vals = [float(x.split()[0]) for x in r["expected"].split(" / ")]  # "20 each"
        if len(vals) != len(ex):
            raise SystemExit(f"extended_rows.csv: {r['helper_or_case']}: {len(vals)} values, {len(ex)} expressions")
        for e, v in zip(ex, vals):
            if e is None:
                continue
            cs.append((9, n, e, v, 10000, f"ext {e}", "FAIL", r["source"]))
            n += 1
    return cs


def helpers_in(src):
    """names of rs:: / mu:: helpers this bot defines (a helper a bot lacks is skipped, not failed: older bases predate it)"""
    import re
    txt = "".join(open(os.path.join(src, f), errors="replace").read() for f in ("rs.h", "mult.h", "rules.h", "multipliers.h") if os.path.exists(os.path.join(src, f)))
    return set(re.findall(r"^inline\s+(?:constexpr\s+)?(?:const\s+)?[\w:&<>]+\s+(\w+)\s*\(", txt, re.M))


def used(expr):
    import re
    return set(re.findall(r"(?:rs|mu)::(\w+)\s*\(", expr))


def gen_header(cs, has_mult):
    out = ["// generated by tools/lab/rulestest.py: never edit, never ship (imports env.cxe_probe)", "#pragma once",
           f"#include \"{'rules.h' if NEW_LAYOUT[0] else 'rs.h'}\"", "#include <cmath>"]
    if has_mult:
        out.append(f"#include \"{'multipliers.h' if NEW_LAYOUT[0] else 'mult.h'}\"")
    if NEW_LAYOUT[0]:
        out += ["#include \"champ_heart.h\"", "#include \"champ_ren.h\""]
    out += ["extern \"C\" __attribute__((import_module(\"env\"), import_name(\"cxe_probe\"))) void rt_probe(unsigned, unsigned, unsigned, unsigned, unsigned);",
            "namespace nova_rtest {", "inline void run() {"]
    for kind, i, expr, _, scale, _, _, _ in cs:
        if kind == 8 and not has_mult:
            continue
        out.append(f"  rt_probe({kind}u, {i}u, 0u, 0u, static_cast<unsigned>(static_cast<int>(std::lround(static_cast<double>({expr}) * {scale}))));")
    out += ["  rt_probe(999u, 0u, 0u, 0u, 1u);", "}", "} // namespace nova_rtest"]
    return "\n".join(out) + "\n"


NEW_LAYOUT = [False]


def adapt(expr):
    """new layout: the passive formulas moved to the champion files and gold takes Vesper's percent instead of a bool"""
    import re
    expr = expr.replace("rs::ren_ret(", "nova::ren_layer::retaliation_damage(").replace("nova::mu::hor(", "nova::heart_layer::damage_mult(")
    pct = lambda b: "rs::rules().vv_pct" if b == "true" else "0"  # noqa: E731
    expr = re.sub(r"rs::gold_mult\((\d+u), (true|false)\)", lambda m: f"rs::gold_mult({m.group(1)}, {pct(m.group(2))})", expr)
    return re.sub(r"rs::kill_gold\((.+), (true|false)\)", lambda m: f"rs::kill_gold({m.group(1)}, {pct(m.group(2))})", expr)


def hsrc(bot, names=("rs.h", "mult.h", "rules.h", "multipliers.h")):
    d = os.path.realpath(f"{REPO}/bots/{bot}") + "/src"
    h = hashlib.sha256()
    for n in names:
        p = os.path.join(d, n)
        h.update(open(p, "rb").read() if os.path.exists(p) else b"-")
    for f in sorted(os.listdir(TABLES)):
        h.update(open(os.path.join(TABLES, f), "rb").read())
    h.update(open(os.path.abspath(__file__), "rb").read())  # a new row set needs a new test copy (b1394: the tag reused the old generated header)
    return h.hexdigest()[:16]


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    bot = a[0]
    if "--base" in a:
        base = a[a.index("--base") + 1]
        stamp = f"{OUT}/passed/{hsrc(base)}"
        if hsrc(bot) == hsrc(base) and os.path.exists(stamp):
            print(f"rulestest {bot}: unchanged (rs.h, mult.h and the tables equal {base}'s, which passed)")
            return 0
    import cxebuild
    src = os.path.realpath(f"{REPO}/bots/{bot}") + "/src"
    NEW_LAYOUT[0] = os.path.exists(f"{src}/rules.h")
    has_mult = os.path.exists(f"{src}/mult.h") or NEW_LAYOUT[0]
    have = helpers_in(src)
    allc = build_cases()
    if NEW_LAYOUT[0]:  # adapt before the 'bot lacks this helper' filter, or the moved helpers' rows would be skipped silently
        allc = [(c[0], c[1], adapt(c[2])) + tuple(c[3:]) if c[2] is not None else c for c in allc]
    cs = [c for c in allc if used(c[2]) <= have and (c[0] != 8 or has_mult)]
    skipped = sorted({n for c in allc for n in used(c[2]) - have})
    tag = hsrc(bot)
    tb = f"nova_rt_{tag}"
    if not os.path.isdir(f"{REPO}/bots/{tb}"):
        r = subprocess.run(["sh", f"{REPO}/tools/lab/newbot.sh", bot, tb], capture_output=True, text=True)
        if r.returncode:
            print(r.stdout + r.stderr)
            return 2
        td = os.path.realpath(f"{REPO}/bots/{tb}") + "/src"
        open(f"{td}/rtest_gen.h", "w").write(gen_header(cs, has_mult))
        main_f = f"{td}/main.cc" if os.path.exists(f"{td}/main.cc") else f"{td}/main.cpp"
        m = open(main_f).read()
        anchor = "\twhile (true)\n\t{\n"
        if m.count(anchor) != 1 or "#include \"brain.h\"" not in m:
            print("rulestest: main.cpp layout changed (anchor not found)")
            return 2
        m = m.replace("#include \"brain.h\"", "#include \"brain.h\"\n#include \"rtest_gen.h\"", 1)
        m = m.replace(anchor, anchor + "\t\t{ static bool rt_done = false; if (!cambc::is_draft() && !rt_done) { rt_done = true; nova_rtest::run(); } }\n", 1)
        open(main_f, "w").write(m)
    try:
        sys.path.insert(0, f"{REPO}/tools/lab")
        import idopp
        so_t, so_o, exe = cxebuild.build_bot(tb), cxebuild.build_bot(idopp.id_opp()), cxebuild.build_host()
    except (SystemExit, subprocess.CalledProcessError) as e:
        print(f"rulestest: the test copy did not build ({e})")
        return 2
    out = f"{OUT}/{bot}_{time.strftime('%m%d%H%M%S')}"
    os.makedirs(out, exist_ok=True)
    mp = "/data/USER/ablproj_4.0.0/maps/04crossroads.map26a"
    subprocess.run(["nice", "-n", "10", exe, so_t, so_o, mp, f"{out}/g"], env=dict(os.environ, CXE_PROBE=f"{out}/p.tsv"),
                   capture_output=True, timeout=600)
    got, champ = {}, None
    for ln in open(f"{out}/p.tsv") if os.path.exists(f"{out}/p.tsv") else []:
        x = ln.split()
        if len(x) < 8 or x[1] != "0":
            continue
        if champ is None:
            champ = x[2]
        if x[2] != champ:
            continue
        got[(int(x[3]), int(x[4]))] = int(x[7]) if int(x[7]) < 2 ** 31 else int(x[7]) - 2 ** 32
    if (999, 0) not in got:
        print(f"rulestest {bot}: the test copy reported nothing complete ({len(got)} values; fuel or a throw?) - see {out}")
        return 2
    fails, warns, n, lines = 0, 0, 0, []
    for kind, i, expr, exp, scale, label, sev, srcref in cs:
        if kind == 8 and not has_mult:
            continue
        n += 1
        v = got.get((kind, i))
        val = None if v is None else v / scale
        ok = val is not None and (abs(val - exp) < 0.5 / scale + 1e-9 if scale > 1 else val == exp)
        lines.append(f"{'ok' if ok else sev}\t{label}\texpected {exp}\tgot {val}\t{srcref}")
        if not ok:
            fails += sev == "FAIL"
            warns += sev == "WARN"
    open(f"{out}/rows.tsv", "w").write("\n".join(lines) + "\n")
    bad = [ln for ln in lines if not ln.startswith("ok")]
    head = (f"rulestest {bot}: {n} rows ({'with' if has_mult else 'without'} mult.h); {fails} FAIL, {warns} WARN"
            + (f"; skipped (helper absent in this bot): {', '.join(skipped)}" if skipped else "")
            + f" -> {'FAIL' if fails else 'PASS'}")
    rep = head + "\n" + "\n".join("  " + b for b in bad[:40]) + ("\n  ..." if len(bad) > 40 else "") + f"\nrows: {out}/rows.tsv\n"
    open(f"{out}/report.txt", "w").write(rep)
    print(rep, end="")
    if not fails:
        os.makedirs(f"{OUT}/passed", exist_ok=True)
        open(f"{OUT}/passed/{tag}", "w").write(bot + "\n")
    if "--keep" not in a:
        for p in (f"{out}/g.repl26a",):
            if os.path.exists(p):
                os.remove(p)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
