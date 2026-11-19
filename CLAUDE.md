# cambc

We build **nova**, our Cambridge Battlecode 2026 bot: C++ compiled to WASM (client cambc 5.0.0, engine 3.0.0). Team **BattleCats**. 

**Rules:** GameRules.md is the authority; also BotAPICpp.md, BalanceChanges.md. **Re-read the GameRules.md lines a decision depends on after every context reset.** Edge cases the handbook leaves out: docs/interactions.md.

**Reading the bot:**
- docs/nova-design.md: do not overfit; no map identity.
- Layout (live since v626): docs/code-map.md says which file owns what; docs/rules-gaps.md lists where the code contradicts the rules; docs/renames.tsv maps old function names to current ones.
- Never read whole .cpp files. One call per code question: `python3 -I tools/lab/card.py NAME [--code]`; find with `python3 -I tools/lab/codeindex.py bots/B --grep WORD`; compare with `python3 -I tools/lab/funcdiff.py bots/A bots/B`.
- Testing commands: cambc-lab skill. Before proposing or judging an idea: `python3 -I tools/lab/ask.py "words"`.
- Build and replay-walking subagents: general-purpose agents; there are no dedicated agent definitions, so brief each with the rules it needs (condor-work/reports/primer_core.md).

## 0. Taking over
1. This file, GameRules.md.
2. First line of /data/USER/st/bq/live.txt must match §1.
3. Tail of condor-work/reports/builder_queue.md (~60 lines), LIVE lines in condor-work/reports/subagent_primer.md, `python3 -I tools/lab/armq.py list`, tail of /data/USER/st/bq/shipwatch.log, condor-work/reports/idea_queue.md.
4. `ListAgents` for sessions and subagents; `CronList` for the Builder's crons (recreate any missing: §0a).
5. Memory index MEMORY.md holds the owner's standing preferences. Verify any file or flag a memory names.

## 0a. Automation
- **Builder crons (session-only; recreate in a new session):** BUILDER TICK :09/:39 (`tools/lab/since.py --mark builder`, react only to SUBMITTED, FAIL/INCONCLUSIVE, dead daemon, /data >= 95%), RESUME CHECK :17.
- **Daemons** are `nova-*` transient user systemd units on HOST (main machine since 9 Nov ~14:40Z; HOST's /var was full), plus pilotd. Linger is off: the units stop if every session on HOST ends. Condor goes through a remote schedd named in bq/pilotd.env (HOST since 9 Nov 20:56Z: HOST rebooted ~18:07Z, HOST's schedd went at 20:55Z; HOST has none); healthwatch fails over to the first answering host in bq/schedd_candidates.txt. They run only once started: exact commands are in /data/USER/st/bq/daemons.txt; `rm bq/*.nowatch` first. Once up, healthwatch restarts them (touch bq/NAME.nowatch before stopping one on purpose): shipwatch (auto-ships on PASS), armq, livepipe, quotaguard, memguard (9 Nov: stops the biggest job under 5 GB free), freshpool, critgame (skips auto runs while /data/USER/st/crit/AUTO_OFF exists), ladderclimb. Check: `python3 -I tools/lab/healthwatch.py --check`; alarms show in since.py.
- **Unranked:** only tools/lab/ladderclimb.py: the main climb (stops on a loss) and 5 side lanes, nova-ladderclimb-side and -side1..4 (`CLIMB_DIR=/data/USER/st/climb_side[1-4] CLIMB_NO_WAIT=1 CLIMB_SLICE=i/5 CLIMB_QUOTA_CAP=95`, owner 8 Nov: use the quota fully, 5 teams at a time; losses flagged critical). Top-3 lane nova-ladderclimb-top3 (owner 9 Nov: more top-3 data): `CLIMB_DIR=climb_top3 CLIMB_TEAMS=<Mite,SBG,Fish ids> CLIMB_FULL=1 CLIMB_FLAG_BG=1 CLIMB_SET=top3 CLIMB_QUOTA_CAP=60 CLIMB_QUOTA_IDLE=85 CLIMB_YIELD_TO=<the 5 rotation dirs>` (85/h while the rotation is idle, 60 once it has work); lanes run with systemd Restart=always, every map on each live version, all games in climb_top3/games.tsv, replays (wins too) in /data/USER/plat/top3_vNNN. Other loops are off. Never Elo-gated rollbacks.

## 1. Live state (shiprec.py updates this)
- **Live: bots/nova_b16468_fbk1bz9 = v919** (HAND 2026-11-13T23:49:05Z, TRUNK nova_ptk_fbk1bz9233827711651): v918 + FBK1: farm break for a won fight (owner submit; fresh .5105 n1000, .5062 n2000, BIG .503, panel +.003, 0 faults) [affects 38.0% of maps]. HAND (shipcheck 16468 FAIL): h2h 0.5030 [0.493, 0.513], pooled 0.5062 [0.4981, 0.5144] n 2000, fresh 0.5105 [0.499, 0.522], panel D +0.003, cap5 fuel 0.96x. Rollback: submissions activate 918.
- **v918** = bots/nova_b16460_shv3fsy (auto 2026-11-13T23:35:23Z, TRUNK nova_ptk_shv3fsy232123711645): v917 + SHV3: spawn-reach heavies hit from spawn tiles; rare PASS on v917 (changed .813 n420, fresh no-harm .4992, ~1% of maps). Shipcheck 16460 PASS: rare 0.813 [0.784, 0.842] n 420, fresh 0.8131 [0.784, 0.842], panel D +0.032, cap5 fuel 2.00x. Rollback: submissions activate 917.
- **v917** = bots/nova_b16457_blt1vrx5k (auto 2026-11-13T23:19:36Z, TRUNK nova_ptk_blt1vrx5k231416711638): v916 + BLT1: Prism team-bank latch; full bar PASS on v915 (pooled .5045 n2000 z +2.60) + v916 confirm .5010 n1000, 0 faults [affects 5.0% of maps]. Shipcheck 16457 PASS: cap5 fuel 1.00x. Rollback: submissions activate 916.
- **v916** = bots/nova_b16447_cnfavrx5 (auto 2026-11-13T23:13:23Z, TRUNK nova_ptk_cnfavrx5230055711629): v915 + CNF2: carry stays near the mate group (CNF_BITS=2 CNF_GAIN=2); full behaviour PASS on v915: pooled .5122 n2000 z +1.87, BIG .5141, panel -.007 [affects 33.5% of maps]. Shipcheck 16447 PASS: h2h 0.5141 [0.497, 0.532], pooled 0.5122 [0.4994, 0.5251] n 2000, fresh 0.5040 [0.486, 0.522], panel D -0.007, cap5 fuel 1.10x. Rollback: submissions activate 915.
- **Baseline:** first non-comment line of /data/USER/st/bq/baseline.txt (now v625 nova_b2769_ems_glate, the only bot left after the owner's 8 Nov purge; no drift read behind it).
- **After a ship:** `python3 -I tools/lab/shiprec.py "WHAT CHANGED"` writes best_model.txt, §1 (keeps the newest 3 version lines), the primer LIVE line and builder_queue.md (shipwatch writes submissions_log.md). Build on the new live.
- **Drift:** after a few ships, `gate.py LIVE BASELINE --lane behaviour --no-style --no-a --keep-fresh --tag driftvNNN`; a pass promotes that version in /data/USER/st/bq/baseline.txt; below .50 triggers a rollback review.
- **Rollback:** `submissions activate N` via platlock.

## 2. Owner's standing rules (decide yourself; ask only when truly blocked)
- **Autonomous shipping:** find improvements and ship on your own judgement, including hand-submits under a rule. Minimise a candidate's drawback and retest first. Never work around a classifier denial.
- **Local tests decide; Elo is extra.** New UNSAVED per-run maps every test, half pathological, plus the saved bank as no-harm. A gain must persist on a second fresh set. Never tune on a fixed set. Report a local pass as a local result, never as a proven gain.
- **Top teams.** Size the ceiling; foe comparisons use only SBG, Mite and Fish, as context. Filter them by team id, never by name (SBG changes its name often: seen as 'stellar best girl' and 'prism best fih'): SBG 547efb5b-57e5-4355-8501-3b331f506d62, Mite ee83f5e5-bcad-4923-86b4-b79ea6083d2e, Fish 1890540d-1ffc-4847-adbf-d0d08772f268 (ids checked on the ladder 13 Nov). Owner 13 Nov: "Add Claudus" was reversed by his later answer "Exclude Claudus" (AskUserQuestion); the only teams that matter are the top 3, and no new work goes to lower-ranked teams (Claudus, pdi, Supaswag, Kungarna, Sponge, Nyx).
- **Ship fast.** Ship single candidates the moment they pass; never leave the loop idle. At most ~20 build agents at once (owner 10 Nov ~22:4xZ "full throttle", back from the 5-agent cap set at 22:15Z). Parked handoffs live in condor-work/reports/parked/bNNN.md.
- **Be dynamic:** decisions re-evaluated each turn from current information, not fixed thresholds or roles. Bodies mix; no designated roles.
- **No arbitrary Step 0 bars (owner 12 Nov, confirmed in the Coordinator chat: "if it does not fire then there is no point in testing as nothing has changed. Yes get their normal bar so if behavioural check and etc"):** a Step 0 count or firing bar ("GO >= .3/g", KILL under .1/g, produced/convergence rows, outcome-share thresholds) is information and no longer stops a line. A bit that fires 0 times changes no game and stays closed. A mechanism that fires at all is built and gets a regular played read on its lane's normal bar (behaviour/fix/rare as in section 5, point > .50 and the usual harm rows); a read above .50 is followed up, not closed. Lines already stopped by such a bar despite real firing are re-queued by the Builder.
- **Map types:** a rule bad on some map types doesn't activate there. The type is decided at draft from map features and stored in draft memory (no map names). First find WHY it loses there, pre-register the gate, confirm on NEW maps of that class plus the whole pool. Strata: draft-time features only.
- **Draft:** map features only, never enemy picks or map identity. Test as swaps v the live lineup. One exception (owner 13 Nov ~15:0xZ, AskUserQuestion answer to the Builder on PMR bit 1, mirroring a foe Prism pick seen in an earlier draft round): "Sure but do not depend on this too much, would need live data and also keep in mind we can always swap pick order to mess with the others".
- **Failures:** adapt once per chain (reason, one pre-stated change, then close; ledger /data/USER/st/bq/failure_chains.md). A plain re-arm is not an adaptation. Timeouts never close an idea: list unfinished reads in bq/pending_reads.txt. Small positives that miss a bar go to the failed-positive bank.
- **Minor details count:** every verified bug gets fixed; small fixes read in bundles.
- **Switches (8 Nov):** a ship needs no runtime switch (they cost fuel); use one only to prove identity and count firing before arming.
- **Owner replays** (`https://2026a.battlecode.co.uk/game/visualiser/<match id>`) go straight to the analysts. `sh tools/lab/platlock.sh /data/USER/cambc400/bin/cambc400 matches show <id> --json`; `... matches download <id> -o DIR/r.zip`; `python3 -I tools/lab/replay.py info|track|show|presence R --us A|B`; `python3 -I tools/lab/puppet.py MATCH_ID` re-plays exactly until the first change. Reply with what happened, the cause if known, and what is being done.

## 3. Sessions (one owner per task)
| Session | Role |
|---|---|
| Builder | Decides, delegates builds, arms, keeps records. Log: builder_queue.md |
| Planner | Owns econ/assess design, reads and arms; plans owner ideas; Builder relays build agents |
| Econ, Combat, Deep analysis, Top analyser | Analyse losses and owner replays, send specs (base file:line, per-bit condition + action, firing/g, kill rule). No builds |
| Rule Checker | Rule and read checks; no code |
| Tool Builder, Tool Builder 2 | Own the pipeline tools and daemons |
| Build agents bNNN | Measure, build behind a runtime flag, prearm, report `DONOR:BASE + FLIP` with numbers. Never submit |

Prereg in /data/USER/st/bNNN/prereg.md with a `date -u` stamp before score runs. Rules for agents: condor-work/reports/primer_core.md.

## 4. Workflow: idea -> live
1. **Measure first:** firing count before any mechanism story; name the binding decision (file:line) and ceiling. Diag copies: integer writers `tools/lab/dgkit.py` or `tools/lab/dglog.h` (release `puppet --diag`), never printf.
2. **Build on live:** `sh tools/lab/newbot.sh <base> nova_bNNN_NAME` (never `cp -r`). Own feature file (on the refactored layout there are no feature files: the code goes in the module that owns the decision, and `newfeat.py BASE NAME FLAG --module M` adds the flag), runtime data flag table (see GT_FIX_TAB in econ.h), flag read first (`FLAG_ON && helper()`), one bit per idea, unique prefixes. Variants: `sh tools/lab/flip.sh <base> <new> "FLAG=V ..."`.
3. **Prearm:** `python3 -I tools/lab/prearm.py DONOR:BASE "FLAG=V" LANE "SUBJECT" [SLUG] [--rare N] [--bugbar] [--no-queue]` (base, brace, flips, merge, identity 40/40, fault, fire; on PASS it adds the armq line unless --no-queue). A replaced live call may be a flag-first wrapper in a feat_* file.
4. **Smallest read that decides:** `tools/lab/inforead.py CAND BASE --who bNNN [--n 300]`, or `tools/lab/gate.py CAND BASE --lane fix|behaviour [--tag T] [--keep-fresh] [--no-a]`. Several arms: `armfarm.py`, then confirm on maps the arm was not picked on.
5. **Arm:** `python3 -I tools/lab/armq.py add DONOR:BASE|idea:NAME "FLAG=V" fix|behaviour|draft "type(area): summary <= 60 chars" [SLUG] [--bugbar] [--rare N] [--parambar] [--front]`. armq merges on live (private trunks, batches); shipwatch runs shipcheck and auto-submits on PASS. `armq.py list|promote|drop`. Stored ideas: `tools/lab/ideastore.py` (`restore NAME` for a retired bot).
6. **Hand-submit** only under a rule (e.g. owner bug bar): `python3 -I tools/lab/handsubmit.py vNNN BOT "<note <= 80>"` (11 Nov: takes the submit lock, checks live.txt and the platform's newest upload, submits, and writes live.txt; a hand-submit missing from live.txt let an auto-ship land on top without it), then shiprec.py. Disarm autoship first if armed. The old raw form, which does NOT write live.txt:
   ```
   flock /data/USER/plat/.shipcheck_submit.lock sh -c 'h=$(head -1 /data/USER/st/bq/live.txt|cut -d" " -f1); [ "$h" = vNNN ] || exit 3; sh tools/lab/platlock.sh /data/USER/cambc400/bin/cambc400 submit -n "$0" bots/NAME' "<note>"
   ```
- **Reopening:** after a big shared-mechanism change, `tools/lab/reopen.py`; retest once on current live, a fail closes it on that base.

## 5. Bars (do not move them; shipcheck.py is what runs)
Every point bar is >= .50, the bug bar too (owner 9 Nov: "Yes, .50 for all"); only the trunk-code row uses .495. Judge on map pairs (both seats), never repeated runs. Compare a candidate with its base, not in mirrors.

| Lane | Bar |
|---|---|
| Behaviour | FRESH-LED (owner 11 Nov ~16:2xZ; SC_FRESH_LED=0 restores the old read): sequential read on NEW fresh maps only (half weird) at 1,650 -> 3,300 -> 8,100 -> 12,000 maps: z 4.0 / 3.52 / 1.50 / 1.30; stop at LOS < 50% after the 1,650 look, < 60% after 3,300, and the 12,000 look only when the 8,100 look's LOS >= 85% (owner 12 Nov ~13:4xZ, 'speed up iterations': smaller first reads; sim alpha .070, null mean maps -23%; bq/seqbar.txt.bak_1112_3look_3300 restores the 3-look form, which owner 12 Nov ~03:4xZ had set), fresh point > .500 at the last look. FRESH-FIRST (owner 12 Nov ~14:0xZ, "fewer tests on each set" while pilots are short): with < 25 alive pilots (or bq/fresh_first) the 1,650 look plays alone; below .50 the check ends FAIL there, else BIG, panel and info legs start and reuse that read (SC_FRESH_FIRST=0 off). HALF NO-HARM (owner 12 Nov ~15:1xZ, "for now sure, but when load recovers go back to default"): under the same < 25 pilots, BIG plays 1,000 maps and the panel 300 a spar (bars unchanged; SC_HALF_NOHARM=0 off); checks started after the pilots recover play the defaults. DEADLINE TWO-STAGE (owner 13 Nov ~18:5xZ, AskUserQuestion answer "Two-stage", verified in the Tool Builder transcript; bq/seqbar.txt): until 21:00Z looks 1,000 / 2,000 / 4,000 at z 3.0 / 2.2 / 1.50 (LOS stops .50 / .60, alpha .062); from 21:00Z (timer) looks 1,000 / 2,000 at z 2.4 / 1.60 (alpha .057); BIG no-harm 1,000 and panel 300 (bq/half_noharm); behaviour confirm 600 -> 300; point > .50 and every no-harm row unchanged; backups bq/seqbar.txt.bak_1113_1850 and confirm_maps_beh.bak_1113_1850. Other rows: BIG (live h2h) is no-harm only: point >= .495 and CI upper >= .50; fresh std half >= .495; no kind flag; CONFIRM CI upper >= .50 (a stale PASS, overtaken by a ship, re-reads on the new live; owner 12 Nov ~17:3xZ "if an update passes test it on a smaller subset if it becomes stale": behaviour confirm 600 NEW maps v the NEW live (bq/confirm_maps_beh; 3,300 -> 1,200 -> 600, owner ~22:4xZ 'test it on less stuff but it needs to make sure it is good as some other change could mess it up'), fix and bug-bar confirms 1,200 new maps with LOS >= 80% (owner 13 Nov ~15:2xZ, AskUserQuestion answer "For bugs be more careful", confirmed again in the Coordinator chat: "Yes"; bq/confirm_maps_fix, switch bq/fix_careful; was 300), same point and CI-upper bars); panel pooled CI upper >= 0 (nova_spar_aggro, nova_spar_sbg, nova_spar_fish: a no-harm check; gaps in /data/USER/st/b1682/calibration.md, spawn-pressure band not met); anchor; ubaudit; 0 faults; fuel; death guard. An overtake re-reads from look 1 |
| Fix | FRESH-LED (owner 11 Nov, "fresh-led, harm bound on BIG"; SC_FIX_FRESH_LED=0 reverts): 3,300 fresh maps decide, point >= .50 and CI upper >= .50; BIG live h2h is no-harm only (point >= .495, CI upper >= .50). LEAN while armq has ideas waiting (owner 12 Nov ~02:5xZ "sure apply both"): h2h on BIG2 only (2,000 maps) and no panel; STRICT (full pool + BIG2, panel) when the queue is empty ("if you run out of ideas revert to being more strict") or bq/fix_strict exists; SC_FIX_LEAN=0/1 overrides. Play-changing fixes go on the behaviour lane. Owner 13 Nov (typed in the Tool Builder session, verified in its transcript): 18:36Z "lift the bug and fuel blockers for now ... until a behavioural change passes" (bq/hold_fix_lane off; nova-holdback restores it at the next behaviour ship); then "slow down bug fixes and run a smaller subset of tests" (AskUserQuestion "Halve reads + cap slots": after that ship fix fresh 3,300 -> 1,650, BIG 2,000 -> 1,000, same bars, bq/fix_small); then "as much iteration as possible ... keep doing bug fixes and fuel tricks ... make sure they are not negative" (bq/fix_max = half, binds only while other lanes wait). Ships run until ~23:45Z (owner answer to the Builder, ~18:35Z) |
| Fix, bug bar (`--bugbar`) | Verified bugs (play-changing ones too, owner 9 Nov) or play-identical: the FRESH row decides at point ABOVE .50 (> .50, SC_BUGBAR_FRESH_PT 0.5001) with CI upper >= .50 (owner 12 Nov ~12:3xZ: "Combat fixes could also be odd, make bug bar above 0.5"; ~12:2xZ had raised .4975 -> .50); the BIG live h2h row passes at point >= .50 and CI upper >= .50 (same rulings, was .495 then .4975; SC_BUGBAR_H2H_PT), no CI-lower harm bound; a 1,200-map confirm reads at the same > .50 point, CI upper >= .50; a bug-bar line whose capped cut-offs RISE (cap5 above live, z >= 1.0) needs point >= .50 on both rows (owner 12 Nov ~12:0xZ, row 'bug bar, fuel up'); every other fix row stays |
| Fix, Q1 fuel cut (`--q1bar`, marker Q1BAR=1) | Owner 12 Nov Q1 ("depends on the effect on fuel"): a play-identical cut whose fuel effect is REAL (capped cut-offs z <= -2 on a burning family; Builder decides) reads fresh point >= .495 with CI upper >= .50; BIG no-harm, capped-fuel, cut-off and fault rows as the fix lane |
| Identical fuel cut (IDENT SHIP) | Owner 12 Nov ~14:4xZ: "for non behaviour change fuel cuts once verified it behaves identically feel free to ship it without any more testing as either neutral or improvement". A fix-lane BUGBAR/Q1BAR line that cxeident plays byte-identical to live on every game at unlimited fuel (20 maps, then 100 maps x 2 seats), with same-work fuel <= live and ubaudit rc 0, submits with no played reads (shipcheck ident_ship; SC_IDENT_SHIP=0 off; log bq/identship.log). Owner 12 Nov ~19:2xZ ("with identical fuel cutting changes you can test on a very small subset as obviously not negative"): when ubaudit cannot run (rc 2 or 20 min wait), 300 new fresh maps v live decide, PASS iff CI upper >= .50 (SC_IDENT_SMALL_N). Owner 13 Nov (AskUserQuestion answer, "Yes, gate it"): shipcheck's 'games played differently at 100k' line is GATING: a line with any such game goes to the 300-fresh-map fallback (CI upper >= .50) instead of submitting on identity alone (TB edits shipcheck.py:3385-3388). Any differing game or a ubaudit FAIL -> the usual lane bar |
| Owner bug bar (hand-submit) | Pooled BIG + fresh point >= .50 (owner 10 Nov ~21:35Z) and BIG CI upper >= .50; held-out and fresh not significantly negative; 0 faults; capped fuel passes; Combat clean. A kind/map-type flag needs point >= .50 on its targeted re-read, else drop the row that fires there before submitting |
| Rare (`--rare N`, bq/rarebar.txt) | Few maps change: changed maps decide: >= 400 read (RARE 420), point > .50, LOS >= 95%, no BIG row (owner 9 Nov), usual fuel, death, fault rows. A probe finding a common change re-reads on the behaviour lane. CLASS-BANK reads (owner 13 Nov in the Coordinator chat): 'not rare' is judged on the class's share of the POOL (over ~30% = not rare), not on the share of the bank's maps that change (a bank holds only class maps); the rare bar itself is unchanged |
| Draft (drafter only) | BIG no-harm: point >= .495 and CI upper >= .50 (owner 13 Nov in the Coordinator chat, after g5eg read BIG .4994 at 10% of maps changed; was point >= .50, owner 9 Nov); 1,200 draft-changed fresh maps, half weird: point > .50, LOS >= 95%; panel CI upper >= 0; usual rows. A draft-algorithm change may instead take the behaviour lane. Data-only draft cells: changed fresh >= .55 with lower CI >= .50 (n >= ~150) plus no-harm |
| Parameters (`--parambar`) | Search only on new maps. Fresh n >= 1,140, point >= .5025 (owner 11 Nov, was .505), LOS >= 90%, on top of the lane bars |
| Trunk code (flag 0) | Pooled BIG + fresh >= .495 and CI upper >= .50 |
| Death guard | FLAG = z >= 2 on two sets with the same sign; only reads at 700+ maps count; shipcheck: not (BIG z >= 2.5 and fresh > 0). Deaths are a trade: judge by score |
| Capped fuel | Excess <= max(5%, 1.645 SE, 10% per point of gain), judged on cut-offs (cap5) and exhaustion; heavy turns near the budget fail only when cap5 is above live, else information (rule (a), owner 9 Nov); over it goes to bq/fuelbank.tsv, not closed. LEFTOVER-FUEL lines only (PCQ, owner 12 Nov in the Coordinator chat: split it, "make sure ... to understand regular fuel faults ... poll enough such that it means we don't get screwed next turn ... worst case this should be neutral"): cut-offs BEFORE the turn's actions must not rise above live and regular fuel faults must not rise; exhaustion AFTER the actions is information; flag-on/cache-unused play must be byte-identical; the poll interval is tested, not fixed |

Second reads (each once; don't re-arm hoping for a reshuffle):
- **Near miss** (only failing row): behaviour pooled >= .503 with LOS 70-90%, or fix within .005 with CI upper >= .50: one more 1,200 fresh maps, same bar.
- **Second fresh set for BIG no-harm** (owner 11 Nov ~01:10Z, asked by the Coordinator; Planner's proposal): a behaviour candidate with fresh >= .52 on 1,200 maps whose only failing row is BIG point >= .50 gets ONE second independent fresh set of unsaved maps; if it reads >= .50 with CI upper >= .50, that set replaces the BIG point row as no-harm. Every other row is unchanged (fuel, deaths, faults, panel). Winner's curse still applies: the second set must be maps the candidate was not picked on.
- **Kind flag** (n >= 10, z <= -2.5): blocks only if negative again on one more fresh set.
- **One spar z <= -2.5** (only failure): that spar on 1,200 new maps, point >= 0 and CI upper >= 0; if within noise but negative, one third read pooled.

Reading: h2h v the parent runs about 2x the change v third-party spars; quote the panel with every h2h. BIG-strong / fresh-weak means overfit. Any code change reshuffles most games through fuel timing, so prove gain or no-harm statistically.

## 6. Tools, maps, compute
- **Maps:** BIG = ladderw_nh (bq/bigset.txt). Fresh = unsaved per-run maps, half weird: `tools/lab/stratmaps.py DIR --n N --take --who NAME [--wfams w_a,w_b]`; `freshpool.py --status`. Pathological families: tools/lab/genweird.py, gencruel.py. Held-out sets: validate only.
- **Engine:** 3.0.0 (bq/cxe_engine.txt); batches play the native cxe engine on Condor nodes (bq/condab_engine = cxecondor) with a CLI spot-check; replay-keeping legs use the CLI.
- **Running games:** condab/killgate/gate on Condor via pilotd; `inforead.py status|resume|read`. Run `cambc400 run` only from /data/USER/ablproj_4.0.0; never inside condor-work/proj400. Wait if /proc/loadavg > 40; one local build per agent; `tools/lab/waitreap.py --kill` each health tick.
- **Fixed-lineup bots:** `python3 -I tools/lab/forceteam.py BASE nova_ft_NAME "Kit1,Kit2,..."`.
- **Readers:** tools/lab/replay.py, deaths.py, digest.py TAG --rows, verdict.py, since.py. Channels: `replay.chosen_channel` (a recall start the next turn cancels is not a recall).
- **Live data:** livepipe into /data/USER/plat, digests in condor-work/reports/live/. Unranked sets are designed: judge quality on local reads.
- **Rating (context only):** `sh tools/lab/platlock.sh /data/USER/cambc400/bin/cambc400 ladder --limit 100 | grep BattleCats`.

## 7. Pitfalls
- WASM32 `long` is 32-bit: `1L<<40` == 0; use int64_t / 1LL.
- Read the flag before any work; a flag-0 helper call leaks into play.
- Unique macro prefixes (a clash silently turned SETUP_FUEL off).
- Waiters must end: timeout on every wait, and `[x]` in `pgrep -f`.
- Winner's curse: decide on maps the arm wasn't picked on.
- Changed-map share is not firing: count firings.
- The 10M draft turn can run out of fuel; picks then randomise.
- Store-only draft memory changes play through fuel timing.
- Outcome strata, even on the paired base game, regress to the mean: use draft-time features or a null arm.
- Bundle arming: a bundle armed after another must carry its flips.
- Hand-submit notes over 80 characters are rejected.

## 8. Current state

Current state lives in builder_queue.md (tail), idea_queue.md, bq/failure_chains.md and bq/pending_reads.txt; don't copy it here.

## 9. Where things are
- What the refactor's strips removed: /data/USER/st/deadstrip/nova_rf6_strip and nova_rf6_bake (`deadstrip.py find FLAG`).
- Bots: bots/ holds only the live bot (owner 8 Nov: every older version and all shipcheck opponents deleted, also from /data, with no backup). Owner 8 Nov: ships are judged against the last version (live). The panel and gate.py's STYLE legs now play nova_spar_aggro, nova_spar_sbg and nova_spar_fish (spec_panel3_1108; calibration /data/USER/st/b1682/calibration.md); the nochase2 row is retired. `ideastore.py restore NAME` for retired ones it still holds. CLI: /data/USER/cambc400/bin/cambc400.
- /data/USER is HOST's local disk (HOST's copy is stale since 9 Nov 14:40Z; don't use it): st/bq (live.txt, baseline.txt, shipwatch logs), st/gate/TAG, st/kg, st/bNNN, plat.
- Reports: condor-work/reports/ (builder_queue.md, primer_core.md, subagent_primer.md, idea_queue.md, recent build_bNNN_*.md, analysts/board.md, live/).

## Bot rules
- No map identity in bot code: no per-map tables, switches or fixed drafts.
- Every build places wards and uses what they see; never drop the ward code.
- Never `#if` on a float define. Diagnostic copies use an integer writer (tools/lab/dgkit.py or tools/lab/dglog.h), never printf.

## Safety rules (each one broke something)
- **Delete through `sh tools/lab/rmdata.sh [--dry] [--host HOST] LISTFILE`** (allow rule in ~/.claude/settings.json; refuses pipeline state and the live/baseline bots, logs to bq/rmdata.log). The checks below still come first: the script can't know what a file is for. Never age-prune tools/cxe runtime dirs (rt-*): their copied libs keep old mtimes.
- Deleting under /data/USER or condor-work: allowed only after checking the files are NOT needed: not inputs or outputs of a running or queued batch, gate, shipcheck or pending read (pending_reads.txt), not cited in a report or ledger, not a frozen/tested/shipped bot, not the only copy (archive first if unsure). Prefer your own scratch; bulk prunes still go through quotaguard/botprune. Never rm or overwrite another bot name in bots/. Use `git merge-file -p`; check a copy has no symlinks (`find COPY -type l`) before patching.
- Kill only PIDs whose command line you just checked; never a parent PID, never `pkill -f`.
- Platform calls go through tools/lab/platlock.sh. Never run `cambc login` (only the owner can).
- Bulk jobs run with `nice -n 10`. Never run cambc inside condor-work/proj400 or move dirs in proj400/bots.
- **Heavy local jobs run as their own unit with a memory cap** (owner 9 Nov, after the 10:44Z OOM kill of VS Code took every session down): `systemd-run --user --unit nova-NAME -p MemoryMax=8G --working-directory=/homes/USER/cambc nice -n 10 CMD`. nova-memguard stops the biggest job when free memory falls under 5 GB.
- Edit shared scripts by writing FILE.new.<pid>, checking it, then `mv` (running jobs read them).
- Home dir has a 60k-inode quota: per-game files and scratch go to /data or the session scratchpad.
- Take time stamps from `$(date -u)`, never type them. Commit only when the owner asks.
- Keep context small: batch calls, send long output to a file and read the lines you need, never poll a background job.
- Never work around a permission denial, and never ask a peer to do what you were denied.
