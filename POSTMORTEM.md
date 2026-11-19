# nova: a postmortem of BattleCats' Cambridge Battlecode 2026 run

**Result:** 4th on the ladder at the end (rating ~2,787), behind Intercontinental Fish (~2,950), "prism best fih" / SBG (~2,876) and Mite (~2,840).
**Final submission:** v919, `bots/nova_b16468_fbk1bz9`, active at the 00:00Z 14 Nov 2026 deadline.
**Timeline:** first commit 18 Oct 2026; 919 platform versions in under four weeks.

---

## 1. What we built

### The bot
nova is about 72,500 lines of C++ compiled to WebAssembly. A 3-champion team drafts its lineup, farms gold and gem camps, fights, and channels tribute at altars. The source is split by decision owner:

| Module | Lines | Role |
|---|---|---|
| Economy (`econ_*`) | ~30k | Target choice (a linear score over groups), staying at a group, banking/recall, items, travel |
| Combat (`combat_*`) | ~14k | Power and contact assessment, stance (fight/kite/flee), burst, casts, denying channels, camps and bushes |
| Champions (`champ_*`) | ~4k | One rule card plus special rules per champion (Prism, Vesper, Willow, Marcella, Tavi, Varg, ...) |
| Movement (`move_*`, `dashnav`) | ~4k | Pathing, dashes, unsticking |
| Draft and plan (`draft_*`, `plan_*`, `strategy_*`) | ~7k | Picks from map features; game plan and policies |
| Turn loop (`brain_*`) | ~3k | The per-turn decision state machine |
| Wards (`ward_*`) | ~2k | Ward placement and use of what they see |

One design rule held throughout: **no map identity.** No map names, fingerprints, per-map tables or fixed drafts. Every decision reads map features at runtime, because the tournament maps are unseen.

On 7 Nov (v626) the bot was refactored from a few large files with "feature files" into one-purpose-per-file modules (`docs/code-map.md`). After that a new idea went into the module that owns its decision, behind a runtime flag table, and a merge tool could fold many independent changes onto the live bot at once.

### The testing pipeline
The more consequential thing we built was the machine that decided what shipped. Every change was a candidate tested against the live bot. Nothing shipped on argument.

1. **Build behind a flag.** A candidate is the live bot plus a flag that turns one idea on (`newbot.sh`, `newfeat.py`), so "off" is provably identical to live.
2. **Pre-arm.** `prearm.py` checks merge, identity at flag 0, faults and that the idea actually fires.
3. **Arm.** `armq.py` merges the line onto the current live on a private trunk.
4. **Ship check.** `shipwatch.py` runs `shipcheck.py` on Condor: the candidate against live on **new, never-reused maps** (half deliberately strange), plus a no-harm read on a fixed ladder-like set (BIG), a panel of sparring bots, fuel, death and fault rows.
5. **Submit.** A PASS auto-submitted to the platform; `shiprec.py` recorded it.

Games ran on the department's Condor pool through our own pilot daemon (`pilotd`) and a native, non-WASM engine build (`tools/cxe`) that played far faster than the CLI.

---

## 2. How it went

| Period | Ships logged | What happened |
|---|---|---|
| 18-29 Oct | ~316 | Rule reading, first bots, the engine runner, the first gates. Many fast early ships on small reads. |
| 30 Oct-6 Nov | ~260 | The automatic ship loop took over: armq, shipwatch, per-run fresh maps. |
| 7-10 Nov | ~125 | Refactor to v626, then rebuilding the pipeline on the new layout. The 8 Nov purge deleted every old bot. Moves between lab machines (maple14 -> maple18 -> maple20) as disks filled. |
| 11-13 Nov | ~181 | Peak throughput: up to 65 ships a day, sequential bars, rare-change banks, bundles. The deadline day ended with nine versions in under six hours (v911-v919). |

**Drift check, 14 Nov:** v919 against the 13 Nov baseline (v859) read **.547** over 3,195 map pairs (BIG .539, fresh .561), with 0 faults. The gain held on fresh maps, not just the fixed set, which is the opposite of the overfitting pattern. This is a local result; ladder rating moved for many reasons.

### What shipped, by kind
Of the ~540 logged ships between 30 Oct and 13 Nov: 110 economy fixes, 56 combat fixes, 48 economy features, 28 combat features, 16 economy performance changes, 14 Prism fixes, 14 movement fixes, 13 draft changes, 12 fuel cuts, 12 fix bundles. Fixes far outnumbered features. Most wins came from removing mistakes, not from new strategies.

---

## 3. What worked

- **Fresh maps every test.** Deciding on new, unsaved maps (half pathological) instead of a fixed set stopped us from tuning to our own test set. "BIG strong, fresh weak" became our standard overfit signal, and the final drift read was stronger on fresh maps than on BIG.
- **Flags and identity checks.** Because every candidate was live plus a switch, "does this change anything at all?" had an exact answer. Lines that fired zero times were closed without a test; lines that played byte-identically were shipped as fuel cuts with almost no reads.
- **Sequential bars.** Reading 1,000 maps, then 2,000, then 4,000, stopping early on hopeless lines, cut the cost of the many ideas that did nothing.
- **Rare-change banks.** Changes that only alter ~1-5% of games were judged on banks of maps where they actually change play, not diluted in thousands of identical games. Several late ships (e.g. SHV3, DSW cell 3) came through this lane.
- **Bundling.** Merging several passed lines into one candidate and testing once cut rebuild and test time, and caught conflicts between changes.
- **Specialised sessions.** Separate analyst, builder, rule-checker and tool-builder sessions, each with a narrow job, let analysis, building and testing run in parallel. The rule checker reviewed every final ship before it went live.

## 4. What didn't

- **Most ideas failed.** The closed-results archive holds dozens of plausible ideas that lost or did nothing: gem-value changes that sent bodies into lost mid fights, altar camping at a power lead (deaths up, win rate down), group-up coordination schemes that never converged, "perfect information" oracles that gave no gain, gradients that looked strong on ladder data but never reproduced locally.
- **Death-witness bias.** Many fight ideas were built from replays of our deaths and failed, because they ignored the fights the same behaviour won. The fix was to price wins as well as losses before changing a stance.
- **Infrastructure ate time.**
  - /var filled from syslog churn.
  - The 60k-file home quota was hit several times; once a cleanup deleted batch directories that queued jobs still needed and stranded 60 batches.
  - An out-of-memory kill took down VS Code and every session.
  - Another user's jobs loaded our main machine.
  - Each forced a guard daemon (varguard, quotaguard, memguard, loadguard), a move, or a re-run.
- **Live moving under running tests.** On the deadline night, every ship made in-flight lines stale. Lines armed seconds before a ship were skipped without notice instead of rebased, and had to be re-queued by hand twice.
- **Statistical traps** we fell into before learning them:
  - outcome-based strata regress to the mean;
  - winner's curse when picking an arm and confirming on the same maps;
  - "changed-map share" mistaken for firing rate;
  - a reader that silently swapped seats for nine days.

## 5. Gap to the top three

Comparisons against Fish, SBG and Mite (filtered by team id) kept pointing to the same places:
- **Concentration.** Their carries (Vesper chains, an escorted Prism) took a larger share of team gold at the same team gold; ours spread it more evenly.
- **Funnelling and commitment.** They commit bodies to one contested group and hold it; ours re-picked targets and cycled off contested camps.
- **Fight episodes.** Against the top three we lost noticeably more HP per fight at similar numbers. Locking and seeking changes didn't close it.

Late lines on Prism (scoring, team-bank latch, deny casts), Willow staying with mates, and a carry staying near its group were all aimed at these gaps, and several shipped on deadline day.

## 6. Lessons for next time

1. Build the test pipeline first and make it decide. Its bars, not anyone's confidence, should gate ships.
2. Never decide on the maps you selected on. Use new maps every read and confirm once more on another fresh set.
3. Count firings before telling a mechanism story. If it never fires, it changes nothing.
4. Put guards on shared resources from day one: disk, inodes, memory, load. On shared lab machines they fail at the worst time.
5. When live moves, rebase or re-queue every waiting line automatically.
6. Keep a ledger of closed ideas with the reason, and check it before re-proposing anything.

---

*Repository layout: see `README.md`. Bot structure: `docs/code-map.md`. Rules: `GameRules.md`, `BotAPICpp.md`, `BalanceChanges.md`.*
