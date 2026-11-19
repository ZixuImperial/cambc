# Interactions

What GameRules.md leaves out or words loosely, and what decisions depend on. Everything here was re-run on the engine 3.0.0 sandbox unless marked (replay), which means it was measured in decoded live games and cannot be re-run. `GR:N` = GameRules.md line N. `rc` = API return code. A refused action spends nothing unless stated.

## Turn order
From the rules:
- Each round runs camp respawns, spell and ward updates, camp captures, camp turns, then champion turns [GR:124].
- Champion turns alternate between the teams, and the team that starts swaps every round: A starts round 1 and every odd round, B every even round [GR:36, 124, 128].
- Within a team, higher priority acts first, then draft order [GR:129].
- `set_priority` takes effect from the next round and persists [GR:130].
- Dead champions still get a turn [GR:131].

Measured on the engine:
- The alternation is one body at a time, not team blocks. Sort each team by priority, then interleave them, starting team first. Example, B starting, A's order A1 A2 A0 A3 A4 and B's order B6 B8 B5 B9 B7: B6 A1 B8 A2 B5 A0 B9 A3 B7 A4.
- When one team runs out of bodies, the rest of the other team act in their order. Example, 4 bodies v 3, all priority 0, A starting: A0 B4 A1 B5 A2 B6 A3.
- Body ids follow draft order: team A 0 to n-1, team B from n, with Cassi and Issac adjacent. A priority tie goes to the lower id.
- A dead body keeps its place by priority. Its `set_priority` works and persists past respawn. It reads and writes team memory, and is in nobody's vision.
- `priority()` is next round's value, `prev_priority()` this round's. Both need the body in the caller's own vision, mates included (rc 97).
- Same-round reads (b2236 probe, CLI = cxe, 12 Nov, /data/zw4424/st/b2236/cli2_table.txt): a mate acting AFTER A in round R reads A's round-R set_priority value through priority() at once (zero lag); a mate acting BEFORE A reads A's R-1 value. prev_priority() returns the value set in R-1, i.e. the one scheduling round R. has_completed_turn reads 1 for a mate that already acted this round. My own ward's vision is enough to read a mate; a mate out of my vision, in a bush I am not in (adjacent included, 14 of 15 probe reads), or dead returns rc 97 for priority, prev_priority and has_completed_turn alike.
- Foe has-acted bit (b2263 probe, CLI 3.0.0, 12 Nov, /data/zw4424/st/b2263/cli_probe): a FOE's state & 32 (has_completed_turn) is readable whenever the foe is in my vision (rc 97 otherwise) and matched turn order exactly: 437/437 foes that had acted read 1, 429/429 that had not read 0.
- Foe priority reads (b2300 probe, cxe 3.0.0, 600 games, /data/zw4424/st/b2300/foetab.txt): for a SEEN foe that has already acted this round, priority() returns its next-round value: in all 50,306 cases followable into the next round it equalled that round's prev_priority() (no mismatches; 55,022 acted reads, the rest not followable); before its turn, priority() is the value in force. Same as mates (b2236).
- Ally reads out of sight (b2298 dgkit probe, cxe, 12 Nov, 120 games): sdk_champion_gems on an ally not in my vision returns rc 97 in 96% of unseen-alive turns (62,446/65,126); visible reads are always rc 0. sdk_champion_is_alive on a dead mate reads rc 0 with value 0, so death is readable out of sight. Do not treat an unread ally bag as 0.
- Prism never moves and casts in one turn on engine 3.0.0: 0 of 24,297 Prism cast turns in 625 replays had a move or a second cast; 16,944 also had a basic attack, before or after the cast (RC C702, 12 Nov). Turn-order doubles predicted from round parity + every priority known at my turn are still wrong 8.6% of the time (37% of real doubles missed) because later actors reset priority; median 2.9%/game, > 5% in 41% of games (C702).

What follows when priorities do not change:
- The n-th body of each team acts as a pair, and the pair's order flips every round: A's first in odd rounds, B's first in even rounds.
- So between two consecutive turns of mine, the foe at my place in its team's order gets 2 turns, then 0, alternating. Every other foe gets exactly 1. A body with no foe at its place sees 1 from every foe.
- A priority change can give any foe 2 or 0 once.

## Actions in a turn
- Ranged: walk then basic is refused (rc 41); basic then walk is refused (rc 36). Walk, reset, basic works; a reset restores the attack, not a walk.
- A dash uses neither allowance, but ranged still cannot both walk and attack. Vesper's reach after a dash is 2 + 3 = 5; melee walk, dash, basic reaches 4.
- Excludes-walking spell: walk then spell is refused (rc 126); spell then walk is refused (rc 127); spell then basic works.
- A reset is refused while the attack is still available (rc 26). A ranged walk uses the attack, so walk, reset, basic works; a melee walk does not, so a melee body must attack first.
- A body can dash, walk and place a lock in one turn, so a foe with a ready dash can lock from distance 5, or 3 without one.
- Lock then submit in one turn works; submit then lock is refused (rc 35).
- A cast at a camp my own basic just killed returns rc 30; an attack on a body my cast just killed returns rc 42 (replay).

## Stuns
- A stunned body loses exactly its next turn (rc 21), whichever of my double turns casts it. A second stun on a pending stun does not stack. Timers still tick, and a body stunned on its own spawn still heals at that turn's end.
- `buff_data`: type, duration at +4, value at +8. A pending stun reads duration 1 until the lost turn ends, then 0 until it expires.
- A foe stunned in a round where it acts after me loses that turn, and can then act first next round, before my next turn.
- On a stunned turn every action is refused, including shopping and selling on spawn (rc 33), recall (rc 44), tribute (rc 45), wards (rc 63) and walking (rc 21). `set_priority` still works. A stun on Marcella leaves no stun buff, so she never reads as stunned.
- A stunned awake camp skips exactly its next hit. An area stun cancels one hit of every camp in the area.
- A stun on a SLEEPING camp lasts one camp phase (timer ticks while asleep, GR:124): it cancels the camp's first hit only if the group is woken in the stun's own round (top-3 replays v650-660: first hit same round 202/202 skipped; first hit a round later, stunned camp attacked 196/261). A damage-less stun (Cassi slot 1) rarely wakes a group by itself (attack in R+1 with no hit in R: 43/537, an upper bound). Reader /data/zw4424/st/fablean/cisleepstun.py (CI Analyser, 9 Nov).
- Stuns land on gem and gold clusters [GR:570].

## Multipliers
Damage dealt = base x every modifier that applies. The base is Strength for a basic attack, or ability multiplier x current Focus for a spell. Damage modifiers multiply with each other, on basic attacks and spells, single-target and area. GameRules.md does not say how they combine; this is measured.

**Ability multipliers** (all match GameRules.md on the engine):

| Ability | x Focus |
|---|---|
| Cassi single target | 2 [GR:450] |
| Ryth area stun | 1 [GR:504] |
| Prism stun; area | 1.5; 1 [GR:568, 574] |
| Stellar single target; area | 2; 1.4 [GR:598, 604] |
| Marcella single target | 2 [GR:668] |
| Tavi stun | 1.6 [GR:700]; BalanceChanges:58/208/998 say 1.4 (older entries); the bot reads the engine (make_kit) |
| Ren stun; retaliation | 1.1; 0.2 [GR:756, 752] |
| Heart of Ruin dash landing | 1.5 [GR:826] |
| Willow heal | 3 [GR:724] |
| Varg shield; Heart of Ruin shield | 2.5; 1.5 [GR:794, 820] |

- Current Focus includes shards and Prism's carried gems. Stellar with 3 Focus shards: F 110.5, spell 221. Prism with 100 gems: F 240, stun 360, area 240.

**Damage modifiers:**

| Modifier | Multiplier | Applies to |
|---|---|---|
| Skirmish | x1.1 | damage dealt to champions, not camps [GR:316] |
| Monster | x1.15 | damage dealt to camps, not champions [GR:305] |
| Collectors | x(1 + .01 per completed family) | damage dealt to champions and camps [GR:318] |
| Heart of Ruin passive | x(1 + .5 x missing % of current max HP) | all its damage, including the dash landing [GR:816] |
| Durability | x0.9 | damage taken from champions and camps [GR:307] |
| Jungle | x0.7 | damage taken from camps, not champions [GR:309] |

- Examples: Stellar's 170 spell with Skirmish on a Durability target deals 168.3. A wolf's 20 on a body with Jungle and Durability deals 12.6. Prism with 100 gems and Skirmish: stun 396. Heart of Ruin's landing at 500/1000 HP: 120 x 1.25 = 150.
- Modifiers apply before a shield absorbs.
- Heals and shields are not damage. Collectors does not change a heal or a shield, and Skirmish does not change a shield.

**Collectors:**
- It counts completed emblem families, itself included: alone x1.01, one other family x1.02, three others x1.04. Any family counts, including Greed, Power, Durability and Treasure.
- Two stat variants of one family count once, Collectors included. Shards without a finished emblem count for nothing.
- It applies to basic attacks, spells, splash and Ren's retaliation.

**Splash and retaliation:**
- Varg's splash carries the attacker's modifiers: Skirmish onto a splashed foe, Monster onto a splashed camp, Collectors onto either.
- Ren's retaliation is raised by Ren's own Skirmish, Collectors and Monster (v camps), and cut by the attacker's Durability.

**Gold and gems** (bonuses add, unlike damage):
- Treasure with Vesper Vale is 33% + 10% = 43% [GR:335]. Fractional gold carries over.
- Hunter's +50 is added before bonuses. Vesper kill: 133; with Treasure 143; with Hunter 199 (floor 150 x 1.33; BalanceChanges.md:1220); both 214.
- Marcella's tribute gold takes gold bonuses: 50 gems pay 100, or 110 with Treasure.
- Prospector floors 25% of the holder's share of the whole group's cluster reward, once: one gem cluster solo 7 to 8; two clusters in one group solo 14 to 17. Gold bonuses multiply the Prospector part.

**Timers:** Home makes recall 3 turns [GR:310]. Tribute emblem makes a tribute ceil(0.67 t) [GR:312]. Capture caps the remaining capture time at 3 [GR:313].

## Damage
- Damage never hits allies, from area spells, splash or a dash landing.
- Damage on a foe on its own spawn lands in full; it heals at its turn end.
- Ground area spells need no sight and pass walls. The centre may be a wall, hole or altar; range is measured to the centre.

## Camps
- sdk_camp returns a camp's current HP for any camp in the body's own vision, ward included: 190,502 of 190,571 reads of ward-only camps beyond 9 tiles matched the replay (TB probe, 10 Nov, /data/zw4424/st/tb_wardhp/result.txt). read_visible_camps' 9-tile box is the bot's own cut.
- On a distance tie a camp hits the body earliest in this round's turn order, so among mates the one with higher priority. `set_priority` moves the target from the next round.
- Awake camps hit through walls (p27).
- A camp's attack range is Chebyshev, like champion ranges (GR:254): a wolf (range 3) hits a body at (+3,+3) and at (+3,+2) every turn, and not one at (+4,0) (probe_1109/p96).
- A camp's target (the nearest champion, GR:192) is Chebyshev too: a golem at (15,15) hits (18,18) over (15,19). On a Chebyshev tie it hits the earlier mover in this round's turn order, even when that body is Euclid-farther: (18,18) over (18,15) (b2007 pcnm, 16 runs).
- One empty camp phase leaves a camp awake; two put it to sleep. A respawned camp starts asleep.
- An area spell wakes a camp; one hit wakes the whole cardinal group.
- Camps never regenerate (replay).
- P-JNG1 (b2356 for RC C908, engine 3.0.0 sandbox, 12 Nov; /data/zw4424/rulecheck/p6/pjng1.js, .out): HP lost per camp hit on a Heart of Ruin in reach of one awake camp. Monolith (Str 200): no items 200; Jungle-Str emblem 140; Jungle-Health emblem 140 (max HP 1500); 4 Jungle shards, no emblem, 200 (only the finished emblem gives the passive); Jungle + Durability 126; Jungle-Str + Jungle-Health emblems 140 (no stacking); Jungle + Durability + Heart shield 120: the first hit takes the whole shield then 6 HP (126 total), later hits 126. Elk 60 -> 42 and golem 120 -> 84 with Jungle (x.7). A champion hit on a Jungle body is unchanged (Varg 50 -> 50; with Durability 45). A solo body in reach takes exactly one hit per camp per round (each round lost one hit, r3-r5).
- P-CST1 (b2371 for RC C946 lead 10, cxe release diag v853, 80 games, 13 Nov; /data/zw4424/st/b2371/cstj.out): sdk_camp_group_capture_state reads enemy_capturing (3) and contested (2) while the group is in vision even when no body of ours sees the capturer (834 state-3 and 55 state-2 reads by bodies seeing no foe on the spawn tiles). Out of vision it returns rc 97; an rc-0 read during a true enemy capture was never 0/4 (0 of 4,619).
- P-PKH1 (RC for spec PKH, engine 3.0.0 sandbox, 13 Nov; /data/zw4424/rulecheck/probe_1113/p100_pkh.js, .out; p6/ppkh1.md): a camp woken by damage in round R hits a body entering its reach in the champion turns of R+1 or R+2, and not one entering in R+3 or later. More damage while it is awake with no body in reach does not restart that count (a hit from out of reach at R+1, R+2, or every round, still leaves R+3 free); damage on a sleeping camp wakes it anew. Prism alone, one elk or golem (with or without clusters in the group): s0 from 4, step to 5, s1 from 5 (radius 1 reaches the camp), step back to 4 on t5, s0 again on t8 = 2.5xFocus per 8 rounds for 0 HP over 3 cycles, with her on team A or B (identical; the camp phase precedes every champion turn). An s0 stun on an awake camp skips exactly one camp phase.
- P-PKH2 (RC for b2393 PKH bit 4, engine 3.0.0 sandbox, 13 Nov; /data/zw4424/rulecheck/probe_1113/p101_pkh2.js, .out; p6/ppkh2.md): Prism alone at Chebyshev 5 from two cardinally adjacent elks (one group: hitting one elk makes both attack a body in reach) casting s1 at a tile 4 from her and 1 from both elks, every 8 rounds x3: 0 HP lost and each elk takes 1xFocus per cast, with her on team A or B (identical). Each cast wakes the group and it is asleep again by R+3 (step to 4 at R+1/R+2 hit by both, R+3+ free), so it sleeps between casts. With one elk at 5 and its neighbour at 6, no s1 tile within 4 of her reaches the 6 elk; the 5 elk alone is hit, still 0 HP.

## Capture
- Step on in round R: timer starts R+1, paid at the start of R+6.
- With a Capture-emblem holder from the start, or joining during R+1: R+4. Joining during R+2: R+5. Later: no gain (replay).
- An ally can take over with no restart only if it is on the region before the last ally steps off: an empty moment, even between two turns, resets it (replay).
- Receivers are the allies on the region at payment. A mate arriving the round before payment gets a full share and does not restart the timer.
- Each share is floored and all the remainder goes to the lowest ID: 14 gems among 3 pay 6, 4, 4. Each share then gets its holder's own bonuses.
- A body on any spawn tile holds the group until the round after it leaves. A ward does not.

## Tribute and locks
- Tribute emblem length is ceil(0.67 t): 1-30 gems save nothing, 31-60 save one round, 61-90 two, 150 gems four.
- A tribute started in round R with t ticks lands in round R + t, and counts if that is round 2000 or earlier. One started in round 2000 never lands.
- A stun or a foe lock stops a tribute even at timer 0, before the owner's next turn start. The gems stay in the bag.
- An altar holds one lock per team. A foe can lock an altar we locked, which cancels our channel. While a foe lock stands, our submit returns rc 0 but becomes a hit on it.
- Placing our own lock cancels a mate's running tribute at that altar [GR:240; GR:238 says only enemy channels, but the engine cancels both]. The gems stay in the mate's bag. A mate can still start a tribute after our lock is up, and a second tribute beside a mate's does not disturb it.
- The submit that lands the last hit on a foe lock and a second submit that starts the tribute can share a turn (probe p94). While the lock stands, a second hit in the same turn is refused (rc 125).
- P-LKH1 (b2355, 12 Nov; engine 3.0.0 wasm, p94 harness, /data/zw4424/st/b2355/probe/plkh1.out): a body with 0 gems hits a visible foe lock with a basic attack (`attack(altar_lock)`): 5 -> 4. submit_gems with 0 gems is rc 46 and does NOT hit the lock; only a body with gems gets the submit-to-hit conversion. Hits from different bodies accumulate in one round (B1 5 -> 4, B2 4 -> 3); a second basic attack by the same body is rc 41 (the rc 125 refusal is the submit path). The 5th hit removes the lock at once: the same body's next read is rc 98 (not found), an attack on the old handle rc 42. A body with the altar out of view reads rc 97 for either team's lock (altar_lock_at throws; has_altar_lock returns false).
- P-SPC1 (b2354, 12 Nov; engine 3.0.0 wasm, p94 harness, /data/zw4424/st/b2354/probe/pspc1.out): `set_priority` while channelling works. A tribute channel (A2, 50 gems) calling set_priority(77) and a recall channel (A0) calling set_priority(-55) both return rc 0 with no exception; the channel goes on (still tributing / recalling the next round, gems kept); `priority()` (next) reads the new value at once and `prev_priority()` keeps the old one; the next round's order follows it (r12: B3 A2 B4 A0 B5 A1 and B3 A1 B4 A2 B5 A0 v the baseline B3 A0 B4 A1 B5 A2).
- A lock needs no sight or clear path, and cancels an unseen channel. The last hit on a lock and placing our own can share a turn.
- A tribute channel belongs to the altar named in submit_gems: a lock cancels only the channels opened at the altar it is placed on, even when the body is within 1 of two altars and the lock goes on the other one (probe b2002 ptwa, all 4 orderings). The foe's channel altar is not readable from champion_info; its state right after our lock shows whether the cancel happened.
- `altar_lock_at` returns our lock when both stand; read the enemy's with `sdk_altar_lock(team=enemy)`.
- While channelling, a body cannot act (rc 35 tribute, rc 34 recall). After `cancel_channel` it acts the same turn, so a tributing or recalling foe is a full threat.

## Recall and crystal
- Recall timing (b2433 diag nova_b2433_dgv, v908; RC C1405b): consistent with GR:387. The plain capture-recalls seen off-channel at the S+4 turn start were KEPT SPINS: started at S-1 and converted at S by pending_spin_becomes_recall (econ_opening_finish.cc:180; kept only when left >= 4), so they're prefired, and rs::recall_rounds(home, prefired=true) = 4 is right. Home spins are always cancelled, so a fresh Home recall arrives at S+3 (461/461).
- A hit fully absorbed by a shield still cancels a recall. Splash cancels it. An ally's heal does not.
- While a crystal channels, every action fails (rc 123). It cannot be cancelled (rc 124).
- A foe stun cancels a crystal even at timer 0, and the crystal is lost. Marcella's crystal is not stopped by stuns.
- A pending crystal landing tile counts as occupied for allies and enemies (rc 22, rc 32).
- Foe crystals are listed (`GetTeleports`) for any body that sees the landing tile, from the round after the cast.

## Movement and dashes
- A 2-step dash needs some tile next to both ends as its middle. Blocked by: wall, a living camp visible to the dasher, a visible enemy, an enemy spawn tile, a pending crystal landing. Passes: hole, ally, hidden enemy, hidden camp, dead camp tile, altar, own ward. A foe seen through my own ward counts as visible.
- An unseen foe on a dash or crystal landing tile returns false at no cost.
- After a refused step or dash, that body sees the tile for the rest of the round: a basic attack or a unit spell can hit the foe there. No mate sees it, and the same body loses it next round (rc 97). Repeating the step is rc 22, repeating the dash rc 32.
- Crystal range 3 passes walls and lands on bushes; range 4 is rc 37.
- Maps are symmetric by construction; a spawn is one rectangle of 9 to 16 tiles.
- Chases, for a body walking straight away one tile a turn on open ground, over 12 rounds. Same rank means the foe's place in its team's order matches mine; other rank means it does not:
  - Melee foe that only walks: same rank hits 6-7 times from distance 1 or 2, never from 3+. Other rank hits every round from distance 1, never from 2+.
  - Melee foe that uses a dash: same rank hits 7-9 times from distance 1 to 4, never from 5+. Other rank hits every round from distance 1 to 3, never from 4+.
  - Ranged foe that stops to shoot falls a tile behind per shot: same rank lands 3, 2, 1 shots from distance 1, 2, 3 and none from 4+. Other rank lands 2, 1 from distance 1, 2 and none from 3+.

## Vision and wards
- Bush clusters join only cardinally. A foe adjacent to a bush cannot see a body inside. A ward inside a bush sees its whole cluster.
- A ward does not block movement, can go on a bush tile holding an unseen foe, and on an enemy ward's tile.
- A ward returning false means a mate's ward holds the tile, unseen because sight is not shared (replay).
- A dead champion keeps its ward's vision but cannot place one.
- A champion's vision board includes its own ward's tiles. A bush tile seen from outside is not in the board (probe p95).
- Carried consumables and unspent gold survive a death and the respawn (probe p93).

## Reads
- A visible foe's cooldowns (8 after the cast, -1 per own turn end) and consumables are readable.
- A body reads a foe's gems, items, buffs and HP through its own ward, even after its own death.
- `Champion_IsAlive` needs no sight and always succeeds, so foe deaths and respawns can be dated exactly.
- A mate out of sight reads rc 97 for everything except gold. A foe's gold is never readable: rc 105 (api_not_teammate) whether the foe is seen or not (b1809 probe, 10 Nov: 56,403 reads, all rc 105).
- Team memory writes are seen by later bodies in the same round.
- Camp stuns are readable (`sdk_camp_buffs`): timer 1 after the cast, timer 0 once served.

## Champions
- Cassi & Issac: both bags and one reward go to the killer, whichever body was hit. Each body's 60 ticks are its own, so a kill between their turns brings them back a round apart: the body that had already acted that round returns at D+61, the other at D+60.
- Cassi & Issac pair death in replays: the killer's action log lists the partner as an extra hit [1, partner, -HP_left] at any distance (attacks and spells), and both death events name the same killer. Readers that sum hit-list damage (replay.py hostile_hits) count the partner's remaining HP as damage dealt, and a stun-scan reader sees the dead partner as hit. No other link: a partner's damage or stun never ends the other body's channel (0 cases in 292 ranked + 230 unranked games; ranked 01a1cc96-e07a-7de0 r312; RC X579, 12 Nov). deaths.py already handles it.
- Marcella: her reset is refused until she has attacked, so her stun comes as attack, reset, armed hit in one turn, and the armed state is gone at her next turn start. The armed hit also stuns camps. A damaging stun on her still deals its damage.
- Vesper Vale: +33% applies to gold from captures and kills (wolf capture 53 instead of 40, gold cluster 26 instead of 20, kill 133 instead of 100). Gems are unaffected. Tribute pays no gold to anyone except Marcella, so there is nothing for the bonus to apply to.
- Vendetta: a kill refunds both cooldowns at once. If she has not cast this turn, the refunded dash or reset can be used the same turn; if the reset was the turn's cast, they wait for next turn (rc 27).
- Tavi can sell a whole emblem for full price (150 for 5 shards).
- Tavi can make several sell() calls in one turn: b2204 (12 Nov) saw 3-9 per turn on cxe and CLI 3.0.0 with no rc 131. Despite cambc.h:560's rc 131 text ("already sold this turn"), the engine does not enforce one sale per turn across separate calls.
- Ren's retaliation fires per direct hit, including area spells, a dash landing and camps, while stunned and as he dies; never from splash. Base 20 at F 100; Ren's Skirmish 22; attacker's Durability 18; Monster v a camp 23. An attacker's shield absorbs it.
- Heart of Ruin's bonus uses missing % of current max HP.
- Issac: no Health-to-Strength passive. 'Health also adds Strength' is Ryth's (GR:494, :500: Strength + 1% of bonus health). Issac is base Str 45, +3 per Strength shard, Health +80 per shard (GR:484-488), so 5 Strength shards give 60 and Health shards add none (our all-Health Issac reads Str 45 at r600, ~1,430 HP, n 103, Deep 9 Nov). A cluster (120 HP, 0 Str, GR:186-187) has no armour: hits = ceil(120 / (Str x modifiers)); Monster +15% to camps and Collectors multiply. Str 60 kills in 2 hits; Str 45 needs 3; with Monster 2 hits from Str 53 (52.2 x 1.15 = 60). Attack, slot-0 reset, attack lands both in one turn (the reset is that turn's one cast, GR:118), so no dash that turn.

## Draft and fuel
- A duplicate pick returns rc 14 and a different pick can follow in the same turn. The engine refuses to end a draft turn without a pick (rc 135); the random pick [GR:88] is applied by the runner when a bot fails or times out.
- A fuel-cut turn still counts as an own turn end: channels and recharges tick. Turn order does not change.

## Where GameRules.md is loose
- Ward tile [GR:106 "anywhere within 2"]: walls, holes, altars and enemy spawn are refused (rc 64); a teammate's ward tile is refused (rc 117).
- Ward placement needs no line of sight: a ward at Chebyshev 2 across a 1-thick wall is accepted (ranked 01a1c626-efe2-7d78 r237: body (16,33), ward (14,31), wall at (15,32); 80 of 146 placements in that game had no LoS). Placing a ward uses neither the move nor the attack: ward-then-move, ward-then-attack, move+attack-then-ward and ward-then-cast all occur in one turn (Path Finding, engine records, 12 Nov). Placing during a recall or tribute channel is untested.
- A ward placed this turn updates vision within the same turn: sdk_enemy_occupancy read right after a successful place_ward shows foes the ward reveals (Combat diag nova_dg_wbx2 on v799, 40 games v spar_sbg, /data/zw4424/st/combat_py/wbx/run3: foes added the same turn after 184 of 262 vanished-foe bush wards, 6/611 scout, 24/1972 act). W.enemies is built at turn start, so code that wants the new sight must re-sense (reread units / rebuild the foe list) after placing (12 Nov).
- A ward may be placed on a tile where an ENEMY ward stands (ranked 01a1cdbb-df35-724f r72/r424/r571); only a mate's ward tile is refused (rc 117). Starting a channel blocks other actions that turn, including wards (GR:118; 0 wards placed during a kept channel in 966 team-games; the spin recall is masked at world.cc:186-187) (RC X582, 12 Nov).
- Crystal on walls [GR:149]: it reaches across walls but cannot land on one [GR:161].
- Dash middle [GR:161 is silent]: see Movement and dashes.
- `bc_champion_vision` (visible_tiles) for my own body includes my ward on engine 3.0.0: in 50 games every enemy read beyond 9 tiles (13,816) was in it, so world.cc's `hidden` never fires and `W.enemies_far` is empty while alive (rz641w, 9 Nov; codeaudit #110). The world.cc:350-351 comment says otherwise.
- Enemy-targeted spells and basic attacks can target a foe seen only through my own ward: a Stellar 3 tiles from a bush cluster, with her ward inside it, hit a Ren on an inner bush tile with a targeted cast and a basic attack. Without the ward both are refused (rc 30 'Target must be a visible unit' for casts, rc 42 'Target must be a visible enemy or neutral camp' for attacks). The target test uses the body's own vision including its own ward (GR:367); the spell's range (and the 3/1 basic range) still applies, and one cast per turn holds (rc 27). A mate's ward does not count (vision is not shared, GR:365). Probe probe_1109/p98, 9 Nov.
- A ward may be placed ON a living camp member's tile, including a hidden member on an isolated bush tile (68/68 accepted in 4 ranked games v 4 teams, e.g. owner replay 01a1cf4a-87f0-76af; RC C670, 12 Nov). The owner's own ward reveals that member the same turn and the owner can then hit it (Mite placed + hit in one turn 5 times with no other sight); a mate's ward does not suffice (GR:365). An unseen member refuses basic attacks (rc 42) and targeted casts (rc 30).
- A move onto an unseen camp member's tile is refused at no cost, and the same body can attack that camp in that turn (Mite's Issac r16 in the owner replay; 14 such hits in 01a1cef3): the refused move reveals the occupant to the mover (RC C670, replay evidence, 12 Nov).
