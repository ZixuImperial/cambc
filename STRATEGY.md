# nova's strategy: talking notes for the finals

This explains how nova plays and why, with the reasoning behind each choice. File names point to where each idea lives in `bots/nova_b16468_fbk1bz9/src/`.

---

## 0. The game in one minute: what actually matters

- **Gems win, gold helps.** Gems come from capturing camp groups and only score once **tributed** at an altar. The first team to 1,000 tributed gems wins; otherwise tributed gems at round 2,000 decide, then lifetime gold, then kills.
- **Carried gems are at risk.** If you die, the killer takes your whole bag plus 100 gold, and you sit out 60 rounds. If a camp kills you, the gems are destroyed.
- **Tribute is slow and visible.** It is a channel lasting `ceil(gems / 10)` turns. An enemy altar lock (10 gold) cancels it, and so does dying.
- **Recall** takes 5 turns, keeps your bag, heals you at spawn and lets you shop. Damage or a stun cancels it.
- **Compute is a resource.** Each C++ bot gets 100k fuel per turn: 100x on the first draft turn, 2x on the first play turn. A bot that runs out is suspended mid-thought and resumes next round.
- **Information is limited.** Each champion has its own vision, which allies don't share. Teammates talk through just **8 bytes** of shared memory, plus a **1,024-byte plan** written once during the draft.

So every decision trades **gem income against risk to the bag against time**. Most of nova is an answer to "what should this body do with the next few turns to maximise banked gems, without handing them to the enemy?"

---

## 1. Philosophy: two rules that shaped everything

**No map identity.** Tournament maps are unseen, so the bot never recognises a specific map: no names, fingerprints, per-map tables or fixed drafts. Every decision comes from map features measured at runtime: area, walk from spawn to spawn, gold per gem, how clustered the gems are, how many altars there are and how far, wall and hole share. A rule that is bad on some maps doesn't get a map name. It gets a **map class** computed from features at draft time (`plan_map_classes.cc`).

**Tests decide, not intuition.** Every strategic idea was built behind a switch and played thousands of paired games against the current bot, on new maps generated for that test only. Half of them were deliberately strange layouts. An idea shipped only if it won by a statistical bar. Most ideas, including many that sounded obviously right, lost (section 11). So the strategy below is not a designed plan. It is what survived about 900 versions of selection.

---

## 2. The draft: choosing the team from the map (`draft_*.cc`, `draft.h`)

The draft turn has 100x fuel and sees the whole map, so it does most of the thinking for the game.

1. **Measure the map** (`draft_map_features.cc`, `mapfeat.cc`). Thirteen-plus features: team size, map area, spawn-to-spawn walk, altar count and distance, camp gold, gold-to-gem ratio, the share of gems in clusters and in heavy groups, group count, hole %, wall %, total gems, plus the gem rate available on our side and in the middle.
2. **Value every lineup** (`draft_values.cc`, `draft_value_table.h`). A fitted table gives each champion a value by team size, adjusted by map-feature slopes. Lineup-level terms are judged on the whole team, so complementary picks score together. `draft_lineup_search.cc` searches the lineups exactly.
3. **Explicit-regret pick order.** Picks are simultaneous and one at a time, and champions can be duplicated across teams. So the order we pick in is chosen to minimise regret if a later pick goes wrong.
4. **Swap cells** (`DSW` cells in `draft.h`). Small rules, each tested on its own, that swap one champion for another when map features fall in a band. Examples:
   - Vendetta becomes Marcella on maps with no camp gold.
   - Vesper becomes Ryth where the spawns are very close.
   - Prism becomes Vendetta where camp gems are scarce.
   - Several Vesper swaps on non-pack maps.

   One of these, "DSW cell 3 off", shipped on the last day (v914).
5. **Write the plan.** The draft encodes the team plan into the 1,024-byte draft memory (`plan_memory_encode.cc`): who is in which body slot, who tanks first, who carries gems, the capture order, precomputed travel tables, group and altar data, and the strategy mode. Every champion decodes it on its first turn, so the whole team starts from one shared plan without talking.

**Talking points:**
- *Which champions did you favour?* We ran a carry structure. The primary gem carrier is **Prism**, then **Vesper**; **Marcella** and **Vendetta** are secondary carries, used only when no primary is fielded. Ren, Tavi and Stellar are never drafted, because they consistently tested worse for our play.
- *Did you counter-pick?* Almost never. The value table has **no counter terms**, because the draft reads only map features. Counter-picking on the opponent's picks didn't hold up in testing. The one late exception mirrors a foe's Prism pick under a narrow rule.

---

## 3. The opening (`econ_opening_pick.cc`, `econ_opening_walk.cc`)

On the first rounds, each body picks its first group by **value per walk**: gems plus half the gold, divided by distance + 10, among the groups worth contesting. No body idles near spawn. An opening pick is **held** until something actually changes: the target is taken, a foe appears near me or the target, or a crew mate leaves. Re-ranking every few turns made bodies flicker between targets.

---

## 4. The economy: where most of the bot lives (`econ_*`, ~30k lines)

### 4a. Choosing a target: the linear score (`econ_linear_score.cc`, `econ_choose_target.cc`)
Each body ranks camp groups by **profit per body**:

```
S = value(group) × penalties − time × m
```

- **Value:** gems and gold of the group, weighted by what our team can do with them. Gold is worth more to Vesper (+33% gold) and gems to the carrier.
- **Time:** walking, waiting for respawns and clearing time. Each body pays its own time, so a far group must be much richer to win.
- **Penalties:**
  - the chance we actually get the capture, given the foes around and how contested the area is;
  - a back-of-map factor;
  - a kill-window bonus;
  - crew bonuses.
- **Risk (RISK bit):** expected loss of the bag and the respawn time if foes are close, scaled by HP.
- **Switch margin:** a body only switches when the new target beats the current one by a set factor. This stops bodies dithering between two similar options, which was a real problem we measured (bodies walking back and forth, "re-taking contested groups").

### 4b. Crews and stacking (`econ_crews.cc`, `planner.cc`)
- **Crews:** several bodies take one heavy group together. The bot estimates how fast a crew clears it, including stuns landing on camps, which cancel monster hits. The **stagger** rule lets the first arriver start tanking before the rest arrive.
- **Stacking:** the planner routes captures to the champion who multiplies them. Vesper captures gold-heavy groups (+33% gold). Marcella earns +2 gold per gem she tributes. Prism takes gems, because gems are her damage (next section).

### 4c. Banking: when to walk to an altar (`econ_bank_*.cc`, `econ_tribute_gates.cc`)
The key decision is how big a bag to carry before tributing.
- **The carrier keeps her bag.** The carrier banks only for specific reasons: to win now, before the round-2,000 deadline with room for a retry, at the race deadline, or at the plan's bag cap when a channel can start safely.
- **Why:** Prism gains **+1.5 Focus per carried gem**, and her abilities scale with Focus. A big bag makes her the strongest unit on the map. When we tested banking early with a 150-gem cap, kills fell about a third and the result was clearly worse. Her bag is her weapon.
- **Channel safety** (`brain_tribute_doom.cc`): before tributing, the bot asks whether the channel will die before it completes. It checks known foes' one- and two-turn reach, remembered foes, our HP, and whether a cancel buys anything. A doomed channel isn't started.
- **Racing:** near the end, `econ_bank_race.cc` and `econ_bank_win.cc` compute whether banking now wins the game outright.

### 4d. Recall, healing and shopping (`econ_recall_heal.cc`, `econ_shop.cc`, `econ_items.cc`)
- Recall when low on HP, when a shop is due, or to heal. A recall that would be cancelled by damage isn't started.
- **Willow changes this:** near our Willow, hurt bodies **hold and get healed in place** instead of walking home. That saves the 5-turn recall and the walk back.
- **Items:** each champion has a fixed build head (`item_upgrades.h`, the kit's own key items). After that, emblems are ranked by the value they add to that champion's stats. Ryth values Health as Strength, since her passive turns bonus health into Strength.

### 4e. Territory
We farm **our half fully, plus a few middle groups chosen by map type**, and contest only what's worth it. Testing kept showing that deep raids into their half and fights over every contested camp cost more in deaths than they earned. Mid gold camps are an exception: holding them is worth fighting for, because kills pay 100 gold and flatten the gold race.

---

## 5. Combat (`combat_*`, ~14k lines)

### 5a. Assessing a fight (`combat_assess_*.cc`)
Each turn near enemies, a body estimates both sides' power with a **Lanchester model**: total health × total damage, where heals stretch the fight for the side that has them. Ratios and Focus (ability damage) feed a **stance**: fight, kite or flee. Contact and reach rules decide who can actually hit whom this turn and next, since champions alternate turns.

### 5b. The stances
- **Fight** (`combat_fight_*.cc`): focus the weakest killable target and use burst when it kills (`combat_burst*.cc`). Stuns cancel a target's next turn. Last hits matter, because the kill pays gold and the victim's whole bag.
- **Kite:** ranged champions keep distance from melee threats.
- **Flee** (`combat_flee.cc`):
  - dash away, or step out of every enemy's reach;
  - fire a **parting stun** that costs the chaser its next turn, so the gap holds;
  - fall back on an ally, or retreat to spawn to heal.
  - A flee also decides the shot or nuke to throw before walking.
- **ATS rule (shipped v915):** when we're the clearly stronger side with a visible foe near, the engage bar doesn't rise with what's at stake. A big bag no longer makes a strong team timid.

### 5c. Denial (`combat_deny.cc`, `econ_locks.cc`)
- **Cancel enemy tributes:** walk to a channelling enemy and damage or stun them, or place an **altar lock** (10 gold) to cancel their channel and block them.
- **Locks for us:** a lock lets our team tribute behind it while theirs can't.
- **Prism denial (v910 DNP1):** a rich Prism denies by a safe cast instead of walking into lock range.

### 5d. Camps, bushes and vision
- **Camps:** bushes hide units, and the bot fights from and around them (`combat_fight_bush.cc`).
- **Wards** (`ward_*.cc`) are scored from map features:
  - valuable groups, monoliths most;
  - altars where each team is likely to bank;
  - chokepoints on the shortest routes between spawns;
  - bush clusters next to those routes.

  They score higher where enemies were seen recently. Champions place wards along their normal path, so warding costs no extra turns.

---

## 6. Champions: how each one is played (`champ_*.cc/.h`)

| Champion | Kit essentials | How nova uses it |
|---|---|---|
| **Prism** | Ranged 3; +1.5 Focus per carried gem; stun shot (1.5 × Focus) and area blast | **Primary carry.** Holds a big bag for damage, banks only when safe or winning; later tuning on Prism scoring, an idle-in-reach cast (v915) and a team-bank latch (v917) |
| **Vesper** | Ranged 3; +33% gold from captures and kills; dash 2 | Second carry; captures gold-rich groups; the dash gives escapes and reach 5 |
| **Willow** | Ranged 3, best ranged Strength 55; heals an ally for 3 × Focus | Healer who also clears camps; stays with the most allies (v913, the owner's ask); hurt allies hold near her instead of recalling |
| **Marcella** | Melee, stun-immune; +2 gold per gem she tributes | Secondary carry / front line; immunity makes her the safe channeller |
| **Vendetta** | Melee, Str 65; a kill resets all cooldowns | Secondary carry; chains kills on camps and low enemies |
| **Varg** | Melee; splash to everything within 1 of his target | Camp clearer, especially packed camps |
| **Heart of Ruin** | Melee; up to +50% damage as she loses health | Front line late in fights |
| **Ryth** | Melee, HP 1,200; Strength = 1% of bonus health | Buys health, which is also damage; strong where spawns are close |
| **Cassi & Issac** | One pick, two bodies; if either dies, both die | An extra body for economy, kept out of risky fights (a pair death gives a double loss) |

---

## 7. Team coordination without talking much (`comms.h`, `plan.h`, `squad.cc`)

- **8 bytes, used carefully.** Bytes 0–5 hold one claim per body: the target group, plus a flag for "I'm engaged here". Byte 6 holds an event subject, and byte 7 the event type with a round stamp: enemy seen, enemies seen, group taken, group cleared, help. From that, every body knows what the others are doing and avoids duplicate trips.
- **Agreement by computation.** Bodies don't negotiate. Each one runs the same deterministic logic on the same public facts (the plan, the round number, the public score), so they reach the same answer. Strategy phase switches use this.
- **Help calls** (`brain_help_fight.cc`) pull nearby allies into a fight worth winning.

---

## 8. The strategy-mode framework, and an honest note (`strategy*.cc`)

The code has a framework for whole-game strategies:
- **ALTAR:** altar control, locks, banking behind them.
- **CENTER:** take and hold the middle's heavy groups.
- **ECON:** farm our side and contest only free groups.
- **RAID:** pick-offs and denial in their half.
- **SIEGE:** team sieges of bosses.

Each strategy is a small "policy" of knobs: draft pick bias, item build, gem and gold values, engage and flee bars. The draft could also write a **schedule of modes by round** and **rules that switch mode on the score**.

**In the final bot every strategy's selector is off, so every game plays BASE**, the shared default logic. In testing, none of the named strategies beat BASE across maps. The gains came from improving the shared decisions instead. Say this plainly if asked: the framework exists, and the evidence told us not to switch it on.

---

## 9. Fuel engineering

100k fuel per turn is tight for pathfinding, target scoring and combat search across five bodies. If a turn runs out, the bot is suspended mid-decision. We:
- precompute travel tables, map features and the plan in the 100x draft turn;
- measure "cut-offs" (turns that ran out) for every candidate, as a test row that must not get worse;
- shipped many **play-identical fuel cuts**: code that makes exactly the same moves for less fuel, verified byte-identical over hundreds of games;
- found that fuel saved is often spent by the choice logic anyway, so the real lever was decision quality, not just speed.

---

## 10. How strategy changed over the last day (v911–v919)

| Version | Change |
|---|---|
| v910 | A rich Prism denies by safe cast, not by walking to lock range |
| v911 | A bundle of four verified fixes |
| v912 | Prism scoring fix |
| v913 | Willow stays with the most allies (the owner's request) |
| v914 | Draft: DSW cell 3 off (keep Vesper where it had been swapped to Heart/Varg) |
| v915 | Prism acts when idle in reach, and the stronger side doesn't raise its engage bar with stakes |
| v916 | The carry stays near the group of allies |
| v917 | Prism team-bank latch |
| v918 | Heavies that can reach spawn are hit from spawn tiles (rare, about 1% of maps) |
| v919 | **Farm break for a won fight** (owner's submit): break off farming to finish a fight we're winning |

Most of these push the same direction: **keep the carry protected and committed, and turn won fights into gold and gems**.

---

## 11. What we learned, as answers to likely questions

- **"What was your biggest insight?"** That the carry's bag is a weapon, not just a score. Holding gems on Prism raised her damage enough that banking early lost games.
- **"What didn't work?"**
  - Changing gem values (bodies got pulled into losing mid fights).
  - Camping enemy altars when ahead: deaths went up and the win rate fell.
  - Group-up and "wait for the crew" schemes: they failed on coordination.
  - Giving the bot perfect information in one decision: no gain.
  - Copying patterns from ladder data: they didn't reproduce in controlled tests.
- **"How did you know a change helped?"** Paired games, candidate against the current bot on both seats of the same map, on maps generated fresh for each test. We also checked no-harm on a ladder-like set and against three sparring bots, and checked fuel, deaths and faults. Sequential reads at 1,000, 2,000 and 4,000 maps stopped early when a line was hopeless.
- **"How did you compare with the top teams?"** Three gaps:
  - Their carries take a bigger share of team gold at the same team gold.
  - They commit bodies to one contested group and hold it.
  - They lose less HP per fight at equal numbers.

  Our late Prism, Willow and carry-cohesion changes targeted exactly these.
- **"How did you avoid overfitting?"** Never deciding on a fixed map set, no map identity in code, and a final check: v919 beat our earlier baseline more on fresh maps (.561) than on the ladder-like set (.539).
- **"How big was the effort?"** Four weeks; 919 platform versions; about 540 tested ships in the last two weeks alone. Fixes outnumbered features roughly three to one.

---

## 12. One-paragraph summary for the stage

> nova reads the map during the draft and picks a team around a protected gem carrier, usually Prism, whose damage grows with the gems she holds. Every body then scores camp groups by profit per unit of time, discounted by how likely we are to win the capture. Bodies commit to a target until something real changes, crew up on heavy groups and route captures to whoever multiplies them. Combat weighs both sides with a Lanchester-style power model to choose fight, kite or flee, and denies enemy tributes with stuns and altar locks. The carrier banks only when the channel is safe or the bank wins the game. Everything was chosen by testing: each idea played thousands of paired games on maps it had never seen, and only winners shipped.
