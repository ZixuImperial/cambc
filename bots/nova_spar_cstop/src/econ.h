// Target valuation and selection, crews, capture, banking and tribute, recall safety and shopping, item builds.
#pragma once
#include "common.h"
#include "runtime_switches.h"
namespace nova::mv { struct Threat; } // Runtime switch table, one slot per switch (the DOM commit has its own slot).













namespace nova::econ {
void ks_turn(); // Called by spin_on_turn_end with the flag on, after an attack or cast with the move unused.
void bank_step_turn(); // Called by spin_on_turn_end with the flag on, as the last act of the turn.

// PCAL: calibration of rate_for's fixed penalty multipliers, measured on own choices against three opponent bots over 300 fresh maps
// (realised own income per leg round / rated, Poisson fit per factor band). Own body after the opening only (self == my_slot,
// opened, not a dash group); the bounds stay upper bounds (every bit only lowers a rate). Runtime data flag PCAL_TAB[1], read first;
// 0 = off. Bit 1 CONTEST: contest factor 1 - [3]/100 x alive share x clamp((contest - [2]/100) / (1 - [2]/100), 0, 1) (off: from
// .55, .45 deep). Bit 2 FREE: opportunity_factor's FREE bonus (x1.30) becomes [4]/100 (measured x.74 relative; 100 = no bonus). Bit 4 KILLW:
// the kill-window factor (x1.30) becomes [5]/100 (measured 1.11). Bit 8 PACK: a pack factor pf > 1 becomes 1 + (pf - 1) x [6]/100
// (measured: rated 1.37 realises 1.05).
#define PCAL_BITS 8
#define PCAL_C0 35
#define PCAL_CK 50
#define PCAL_FREE 100
#define PCAL_KW 110
#define PCAL_PK 15
inline constexpr int PCAL_TAB[7] = { 0x5043414C, PCAL_BITS, PCAL_C0, PCAL_CK, PCAL_FREE, PCAL_KW, PCAL_PK }; // slot 0 magic keeps it out of .bss
inline constexpr short ECL_CELL[60] = { 1891, 2091, 2255, 1509, 1164, 2473, 1018, 909, 1545, 927, 691, 1545, 1600, 1982, 1091, 1236, 1218, 1855, 945, 836, 1436, 818, 764, 1436, 1418, 1673, 1673, 1145, 1164, 1200, 855, 745, 1382, 1000, 909, 1382, 1800, 1455, 1000, 1618, 1000, 836, 855, 727, 800, 1091, 1000, 800, 1364, 1691, 1000, 1527, 709, 545, 1473, 982, 1509, 1236, 1164, 1509 };

// GPV GROUP PRICE v3 (runtime data flag, 0 = off, flag read first). Own body only, after the opening, re-read every round from live
// state. Bit 1 G1 GROWTH VALUE OF GOLD: my gold weight x (1 - [2]/100 x (1 - q)), q = rounds the game still runs (emblem_rank's tribute
// projections, min with 2000 - r) / (2000 - r); x [3]/100 once my whole build is owned; a group whose gold completes my next emblem
// (0 < gold still needed <= its gold) adds [4]/100 x 30 gold at my weight. group_bounds_loop's bound carries the same terms. Bit 2 G3 ENEMY
// STRENGTH: rate x (1 - [5]/100 x risk), risk = F^2 / (F^2 + C^2): F = sum over living foes of p x health x horizon dps (foe_of on
// its last read body; unread: my own strength), p = its chance to arrive during the clear (fresh sighting <= [6] rounds, distance a
// = cheb - age/2, spawn: d_enemy - age: a <= 6 .75, <= 12 .15, <= 20 .03; staler: [8]/100 x foe-side share), C = crew x my own
// health x dps; risk = (F/C)^e / ((F/C)^e + 1), e = [9]. Bit 4: with bit 2, the flat enemy_seen penalty is dropped (G3 prices it).
// Bit 64: shadow counters (diag copies): best_group also finds the flag-0 choice from the same ratings.
#define GPV_BITS 15
#define GPV_K1 100
#define GPV_LO 30
#define GPV_NB 50
#define GPV_W3 30
#define GPV_AGE 30
#define GPV_SLK 10 // unused since the amendment
#define GPV_STALE 25
#define GPV_EXP 6
// Bit 8 HFH gate: G1 is off on maps with hole tiles >= [10] % of the board AND gem share in elk/golem/monolith groups >= [11] %
// (static map features, computed once).
#define GPV_HG_HOLE 30
#define GPV_HG_HEAVY 75
inline constexpr int GPV_TAB[12] = { 0x47505631, GPV_BITS, GPV_K1, GPV_LO, GPV_NB, GPV_W3, GPV_AGE, GPV_SLK, GPV_STALE, GPV_EXP, GPV_HG_HOLE, GPV_HG_HEAVY };

// BLF: beliefs about what we cannot see. Flag first, zero work at 0. Bit 1 GPD: an UNKNOWN group's value x (1 - P(taken | zone,
// rounds since seen)) (BLF_PT_U). Bit 2 CEX: a CLEARED group nobody of ours holds: from clear + capture time, value x (1 - P(taken |
// zone, age)) (BLF_PT_C); at clear + capture pay + its respawn it is UNKNOWN (then bit 1 applies). Bit 4 HPF: an unseen foe's HP
// reads full once a recall could finish or it could have walked home (foe_hp_reads_full, foe_strength_lazy). Bit 8 is reserved for
// heading claimants' arrival chance.
#define BLF_BITS 0
inline constexpr int BLF_TAB[2] = { 0x424C4631, BLF_BITS };

enum GroupStatus : std::uint8_t
{
	GS_UNKNOWN = 0, // not seen recently: assume alive
	GS_ALIVE,
	GS_CLEARED,     // every member dead, reward waiting for a capture
	GS_RESPAWN,     // captured, waiting to respawn
};

struct GroupMem
{
	std::uint8_t status = GS_UNKNOWN;
	int respawn_at = 0;   // predicted round the group is alive again
	int seen = -1000; // last round any member tile was in vision
	float hp_left = -1;   // living HP when last seen (-1: full)
	int enemy_seen = -1000;
	int fail_until = 0;   // do not target before this round (unreachable, stuck, lost fights)
	int state_checked = -1000;
	int handoff = -1000;  // round we left the capture to a crew mate
	int awake_seen = -1000; // last round a member was seen awake
	int thr_round = -1000; // last threat_seen blacklist (round), and what it replaced
	int thr_until = 0, thr_prev_fail = 0, thr_prev_seen = -1000;
	int kill_round = -1000; // our kill next to this group with no other enemy near
};

// Activity of the last farm() call (debug accounting).
enum Act : int
{
	ACT_NONE,
	ACT_WALK,
	ACT_WAIT,
	ACT_CAMP,
	ACT_CAPTURE,
	ACT_FOLLOW,
	ACT_IDLE,
	ACT_N
};
extern int last_act;
extern int dbg_path; // debug: last farming branch

void init();
void observe();                 // update group memory and what this body felt (damage, enemies, recalls)
void shop();                    // buy items when allowed (spawn, dead, Tavi anywhere)
void tavi_sell_emblems_buy_greed(); // Tavi sells planned emblems on spawn for a Greed emblem
bool want_bank();
extern int pcf_calm; // the round brain's calm want_bank branch called bank()
bool pcf_hold(); // bank_i refused a channel on this calm turn and nothing hits this tile
int on_way_target(int toward, int left); // a camp that fits `left` rounds on the way to group `toward` (-1: none)
void force_target(int gi); // set my target (the zone crew's entry group while it walks and gathers)
bool bank();                    // walk to an altar and tribute; true if acted
bool ring_breach_turn(); // open the altar ring (one body hits one breach camp); true if acted
bool farm();                    // target, crew and capture behaviour; true if acted
bool idle_move();               // nothing to do: drift toward useful places
bool idle_bank(); // nothing to farm: tribute the bag now (commits to the trip); true if acted
void hs3_bg(long reserve); // the hole-shortcut fields, built in spare background fuel
bool hs3_pending_x(int gi); // OPD bit 4: a top group's hs3 shortcut decision is still pending
void build_bg(); // the shop list in spare fuel after the setup rounds
void dead_end_cache_fill(long reserve);    // static per-group flags (dead ends), filled in spare fuel
int claim_target();             // group to publish in shared memory (-1 none)
bool claim_engaged();
bool opening_done(); // the opening choice is made
bool busy_capturing();
bool leave_respawn_tile();      // step off a spawn tile of a captured group (it delays the respawn)
bool engaged_now();             // tanking/fighting a camp group right now
void note_camp_escape(); // EOX bit 2: stamp cf_esc_round after a camp escape
bool camp_escape_guard_on(); // the bank / capture walks' camp-reach guard after a camp_out escape
bool camp_out();
extern int b957_gh_round; // go_home walked home with the home-edge guard off (camp_out stands down the next turn).
bool camp_reach_flee_tile(vec2 p); // camp_out would flee tile p
extern bool ss_pending, ss_live; // Spawn siege: scan pending; a band map (or bit 2).
void spawn_siege_find_groups();
bool spawn_siege_turn(bool flee); // Spawn siege bit 1 (combat.h): an awake camp of another group hits me and I am not on my target: leave its reach.
bool about_to_capture();        // standing at a cleared group we should capture (finish it before any recall)
// rounds until the capture I hold pays (1..6), or -1 when I am not on the region of the cleared group I capture, or an enemy stands
// on it (contested: the engine clears the timer).
int capture_pay_in();
int camp_hits_before_capture_pay(int pay); // Camp rounds to weigh against a payout pay rounds away (call only with a bit set).
bool idle_escape_holds_capture(); // bits 4/32: a capture under me pays before the camp hits leave less than 15% (call only with a bit set)
void abort_ring_bank_walk(); // A bank walk that turned back (path-fix bit 2).
int field_point_dist(int gi, vec2 p, int ch); // ch (a Chebyshev distance from p to group gi), or the walk when it is a detour
int target_walk(vec2 p, vec2 at); // cheb(p, at) to my target group, by walk where it is a detour
int capture_region_dist(vec2 p); // Chebyshev distance from p to the region of the group I capture (BIG if none)
bool hold_region();              // capture hold turn: stay on the tile, hit an enemy in range
bool wants_heal();              // hurt enough that going home beats the next fight
bool finish_clear_ok(); // PASSIVE HoR/Varg/Ren: hurt, but the clear I tank ends within a few rounds with health to spare
bool finish_low_camp_ok(float frac); // RC9 bit 1: finish a low-health camp
bool want_shop();               // enough gold for the next emblem and a good moment to go home
bool recall_safe();             // nothing can damage us during the whole recall channel
bool go_home();                 // walk home when close, recall when safe, else walk out of reach first; true if acted
bool start_recall();            // recall now (no checks); true if started
void on_recall();               // forget the current engagement
void death_reset(); // a dead turn forgets the engagement and forces a re-rate
#define EH_PCT 10 // The camps hitting me deal at most this % of my current health a round.
#define EH_ENEMY_R 8 // ... no enemy champion within this many tiles ...
#define EH_NEAR 4 // ... and (heal recall) I am within this many tiles of my target group
// within TR_MATE_D at >= TR_MATE_PCT % HP steps to a tile where that mate is the nearest (tie: acted first) champion to the
// attackers and hits from there, instead of drop_target(25); re-tested each round; below TR_FLOOR_PCT % HP: bail out.
#define TR_MATE_PCT 60
#define TR_MATE_D 2
#define TR_FLOOR_PCT 25
#define TR_WALK_X100 85 // my health covers this % of the raw walk-out (every attacker in reach of the tile x escape steps)
#define TR_ENEMY_R 6 // no rotation with an enemy champion this close
#define CR_BAG 60 // A chip with a bag this big risks the bag.
#define RC_CONTEST_X100 45
#define RC_SOON 25
#define RC_WAIT 25
#define RC_ENEMY_R 15
#define RC_AGE 30
void threat_seen(const std::vector<vec2>& foes); // enemies near: mark their groups, drop a target among them
#define DC_SHARE 35 // D holds this % of the camp gems or more ...
#define DC_RATIO 3 // ... and this many times the next group's gems or more ...
#define DC_MIN_GEMS 30 // ... and this many gems or more
#define DC_NEAR_TOTAL 80 // no trigger when D holds this % of all camp gems or more (0 = off, v1)
// with NO attackers gets the DOM commit; D with elk/wolves is left as before. 0 = off.
#define DC_MAX_ATT 4 // elk/gem D only: no golem and at most this many attackers
#define DC_WAIT 40 // at D, wait for a committed mate that can arrive within this many rounds of the first wait
#define DC_FAIL 10 // a crew-wait timeout / no-progress drop blacklists D this long
#define DC_HOLD 4 // a flee near D blacklists it this long and keeps it as the target
#define DC_DECIDE_FUEL 30000 // the free-slot decision runs on a turn that ends with this much fuel or more
#define GT_GEMS 150 // team carried gems (estimate) that start the siege
#define GT_K 2 // bodies at the gate (me included) that start the clear
#define GT_TMAX 25 // > 0: commit only when the whole team (healer, Prism aside) clears the gate within this many rounds (estimate t)
#define GT_WAIT 40 // at the gate, wait this long for committed mates before the usual crew-wait drop
// Resize guard (0 = off): of_scan's OfMask table is (re)sized with om.assign whenever M.ng changes (the first observe on the setup
// turn, then every turn M.groups grows), before the setup-fuel test that may refuse the mask build anyway. Bit 1: when the table
// needs that resize and the fuel left is below the build floor (SF_OF_FLOOR + SF_OF_PER a member) plus OFMASK_RESIZE_PG a table
// entry (the new ng plus the old ones destroyed), skip the resize this turn; of_scan returns false and observe's member loop gives
// the same counts (as on the SF path), and the resize runs on a later turn with fuel. Never fires at plenty of fuel. Data flag
// OFMASK_RESIZE_TAB[1]; the hook reads it first (zero work at 0).
#define OFMASK_RESIZE_BITS 1
inline constexpr int OFMASK_RESIZE_TAB[3] = { 0x54483131, OFMASK_RESIZE_BITS, 300 /* OFMASK_RESIZE_PG */ }; // of_scan's fuel guard runs before the mask build
#define OBK_F0 30000L
#define OBK_FG 900L
// SBL runtime data flags SBL_TAB (0 = off; flag read first, no work at 0). support_turn: an engaged body that sees no attacker of
// its target (hold_attacker has nothing to hold) and has no safe tile by the focus (assume-all reach) would end the turn with no
// move. With the flag it walks to the group until an attacker is in sight. Bit 1 melee, bit 2 ranged.
#define SBL_BITS 1
inline constexpr int SBL_TAB[2] = { 0x53424C31, SBL_BITS };
#define ESH_BASE 12 // ... a body's base stats, in shards, for the gain of a shard
#define ESH_SEEN 10 // ... a foe seen this many rounds ago counts as walking at me since
// Recall hop: a recall (7 rounds with the arrival) plus the spawn crystal hop is a route the walk-side rules do not otherwise price:
// on a map whose altar or mid is 100+ walking tiles from the spawn but within 3 of a spawn tile, bodies would walk the whole ring.
// Runtime data flags, 0 = off, flag read first. Bit 1: the route precompute runs before the intel/ward analyses (else it starves
// until r100+). Bit 2: want_bank's walk and bank()'s recall test see recall + hop. Bit 4: target_turn's travel recall sees it. Bit
// 8: compute_travel prices recall + hop away from the spawn. Bit 16: on the spawn a big-saving route buys the crystal before the
// shop.
#define RWK_BITS 31
#define RWK_SAVE 8
#define RWK_BIG 20 // A route counts only when it saves this over the spawn's own walk; the background precompute bit applies only when a target's walk from the spawn could allow it.
inline constexpr int RWK_TAB[4] = { 0x42383038, RWK_BITS, RWK_SAVE, RWK_BIG };
// Fuel bars: on a map with no walkable altar (and no gate that would open one), a dasher's altar route is not built above about
// 2,600 tiles: prepare's bar is 30k + 22 per tile + 4k against a 100k turn, while a layer really costs about 42k at 100x100, so such
// a body could never bank. Runtime data flag FB_TAB[1] (0 = off, flag read first). Bit 8: the route's layers as stages (launch, then
// field), each with its own measured bar, last in the turn's background block, only down to FB_RES. Other maps: only the eligibility
// test, with no fuel-read work after it.
#define FB_BITS 8
#define FB_RES 24000
inline constexpr int FB_TAB[3] = { 0x46423237, FB_BITS, FB_RES };
// Mid-route hop: a carried crystal is otherwise used only on a trip started on the spawn (spawn_crystal_start). Runtime data flag
// MH_TAB[1] (0 = off), bits: 1 non-dash body, 2 dash body: walking to a crew <= 1 target, hop when the landing within 3 saves >=
// MH_SAVE over the walk (channel priced at 3 rounds), the target will be up by then, and no foe is seen within MH_FOE of me or the
// landing; 4 crew targets too; 8 the bank walk too; 16 no spawn route on this map, but my own walks showed a saving: buy one on the
// next visit. Crystal plan: runtime data flag CP_TAB[1] (0 = off), bits: 1 on a scarce map (no gems, or gems only in walled pockets)
// crystal_plan's fuel bars (150k and 250k on a 100k turn: dead after the first play turn) become real ones, the scan yields at low
// fuel; 2 on a map whose crystal-only gems are >= those I can reach (crystal_gems_scarce) the value bar CRYSTAL_MIN_V is off; 4
// there also CRYSTAL_NEAR is off; 8 there the crystal-only groups' value is x CP_TAB[2]/100 and the crystal comes before the shop;
// 64 on a scarce map only the team's gem carrier (else first tank) makes these trips; 128 the launch is any tile within 3 of the
// landing, foe bar 4 not 8, the nearest free landing if the planned one is held; 256 on a scarce map any bag is banked at once (a
// tribute decides the tie-break).
#define CP_BITS 463
#define CP_PRIZE_PCT 800
inline constexpr int CP_TAB[3] = { 0x43503633, CP_BITS, CP_PRIZE_PCT };
// Walled-off (ACC_TP) groups on maps that are not crystal_gems_scarce would never get a crystal plan (crystal_plan's 150k bar on a
// 100k turn), so crystal_ok was false and no trip was rated. Runtime data flag OWR_TAB[1] (0 = off), bits: 1 crystal_plan_background
// also plans ACC_TP groups worth CRYSTAL_MIN_V on non-scarce maps, with the sliced bars of crystal plan bit 1 (needs CP bit 1); 2
// rate_for drops the contest penalty for ACC_TP groups (their contest is the 1.0 placeholder for 'no walk from home', mapinfo.cc
// step_distances, not a measure of the enemy's reach); 4 the trip's return leg is OWR_RET rounds (a recall: 5 owner turn ends + the
// arrival turn, GameRules) instead of the default return leg (12).
#define OWR_BITS 7
#define OWR_RET 6
inline constexpr int OWR_TAB[3] = { 0x4F575231, OWR_BITS, OWR_RET };
// On a gem-starved map with dash-only groups, dashers would never rate the dash-only pocket next to our spawn (dashnav builds routes
// only on dead turns there: the alive bar 12k + 22 x W x H > a turn's fuel; EXPLORE's hole-launch route is off and its board test
// excludes boards under ~5,100 tiles). Runtime data flag STV_TAB[1] (0 = off), bits, only where the map's gems over all groups <=
// STV_GEMS and the dash-only share of them >= STV_DSH %: 1 EXPLORE bit 1 (hole-launch travel + walk/dash for dash-only groups, on
// any board); 2 EXPLORE bit 2 (no contest penalty for a dash-only group: its contest is the 1.0 'no walk' placeholder); 4 a
// dash-only group whose walk field does not reach me is never 'at the group' (path_dist's Chebyshev fallback can read a small
// distance from the wrong side of a hole, so target_turn would wait there): walk to the launch and dash in; 8 capture() of a dead
// dash-only group from outside its walk field goes through approach_group (launch + dash) instead of step_to_set, which cannot cross
// the hole; 16 the home loop: the hole-launch travel (bit 1) to a dash-only group exists only when it is on our side by route, I
// stand home-side, no mate claims it, no mate is in or coming to a fight (TM2 kinds 4/5) or posted a fresh FIGHT call, and QKW's
// team-quiet test holds (checked every turn); with bit 16, bit 2 (no contest penalty) applies to own-side pockets only.
#define STV_BITS 12
#define STV_GEMS 99999
#define STV_DSH 0
inline constexpr int STV_TAB[4] = { 0x53545631, STV_BITS, STV_GEMS, STV_DSH };
// Runtime data flag UNSEEN_CLAIMANT_TAB[1] (0 = off), bits: 1: rally_present_count and siege_present_count count a claimant I can't see (a mate in a bush
// I'm not in, GameRules vision) as present when I saw it within UNSEEN_CLAIMANT_AGE rounds near the anchor (reach + 4) or within 3 of the rally
// tile and the engine says it is alive (no_mate_arrives_in_time skips such a claimant too); 2: crystal_ok is false when CRYSTAL_NEAR
// applies and the plan's launch tile is more than CRYSTAL_NEAR from home (otherwise the trip was picked, then dropped once the walk
// passed CRYSTAL_NEAR); 4: no_mate_arrives_in_time prices an unseen claimant of the group (unseen_mate_eta: the walk from my last sighting less
// every round since) with no walking credit past UNSEEN_CLAIMANT_AGE rounds (otherwise a claimant last seen long before, walking away, read as
// able to come in time).
#define UNSEEN_CLAIMANT_BITS 3
#define UNSEEN_CLAIMANT_AGE 2
inline constexpr int UNSEEN_CLAIMANT_TAB[3] = { 0x42473535, UNSEEN_CLAIMANT_BITS, UNSEEN_CLAIMANT_AGE };
// Runtime data flag HOLD_BUDGET_FIX_TAB[1] (0 = off; every hook reads it first), bits: 1: the HOLD budget cct_n <= group value would
// reset on any one-round gap in the contest (capture()), so a foe stepping off the far end for a round restarted it and the budget
// never bound. With bit 1 the count runs per group: it resets only on another group or after HOLD_BUDGET_FIX_GAP rounds with no
// contested turn there, and a visible foe on the region (cf_contest) counts as a contested turn too. 2: unused. 4: escape_steps is
// Chebyshev (walls, camps and the map edge ignored). the Prism exit rule's bit 1 (prism_exit_walk_longer) prices the true walk
// (safe_tile_walk_steps) only for a gem-focus kit holding more than the group pays; bit 4 drops those two tests, so every kit's
// tank_turn and camp_holder_bail price the true walk inside the band where the Chebyshev read says stay and a longer walk could flip
// it (safe_tile_walk_steps: once a round). 8: idle_move's cover step home uses home_field_cb (camps blocked) with no f_home
// fallback, so on a camp tile it read UNREACH and a hurt idle body within 7 of home neither stepped home nor recalled; bit 8 falls
// back to M.f_home there. 16: wants_heal's harmless-camps exemption (no heal within EH_NEAR of my target's anchor while camps
// hitting me are harmless) held with no living member in sight, which could make a body alternate between the hidden-member walk and
// go_home; bit 16: the exemption needs a living member of the target in sight.
#define HOLD_BUDGET_FIX_BITS 25
#define HOLD_BUDGET_FIX_GAP 60
inline constexpr int HOLD_BUDGET_FIX_TAB[3] = { 0x42473636, HOLD_BUDGET_FIX_BITS, HOLD_BUDGET_FIX_GAP };
#define MH_BITS 15
#define MH_SAVE 8
#define MH_FOE 6
inline constexpr int MH_TAB[4] = { 0x4D483633, MH_BITS, MH_SAVE, MH_FOE };
#define OFMASK_FAST_BITS 65
#define OFMASK_FAST_K 3
#define OFMASK_FAST_F_X100 60
inline constexpr int OFMASK_FAST_TAB[4] = { 0x42373838, OFMASK_FAST_BITS, OFMASK_FAST_K, OFMASK_FAST_F_X100 };
void om_write(std::vector<std::uint8_t>& mem); // Fast mask build: draft side.
bool om_blind_step(); // Fast mask build: play side.
bool spawn_step();
bool enemy_lock_on(vec2 altar); // Altar lock fix bit 1: the enemy lock on the altar, read directly (both locks may stand).
bool home_round_trip_too_costly(); // MF2 bit 4096
#define EH_R 1850 // Endgame hold: the first round of the rule.
#define EH_FOE_R 8 // Endgame hold: a known foe this close (Chebyshev) makes a long channel unsafe.
#define EH_TICKS 3 // Endgame hold: channels of at most this many ticks still start.
// Slot 1 holds the first round itself (off = 30000), so the only test before EH_R is `W.round >= slot`: the same instructions and
// fuel whether the rule is on or off.
#define EH_PROJ_X100 100 // Endgame hold: % of their tribute rate (last 200 rounds) x rounds left, added to their tributed and known bags.
#define EH_SLACK 60 // Endgame hold: gems they may still capture; the flip test is projection + my bag + EH_SLACK >= ours.
                    // Example: 660 + 0 + 200 = 860 < 865, yet they won with 886 after 26 more captured gems plus her 200.
inline constexpr int END_HOLD_TAB[6] = { 0x454E4448, EH_R, EH_FOE_R, EH_TICKS, EH_PROJ_X100, EH_SLACK }; // slot 0 magic keeps it out of .bss
#define END_HOLD_ON (::nova::W.round >= ::nova::econ::END_HOLD_TAB[1])
// GT_TMAX_BOSS: on a map whose only altar sits behind a monolith gate, the enemy can clear it with a few bodies in about 40 rounds,
// while GT_TMAX 25 is below our own 32-39 round estimate for that gate, SG3 excludes gates and rate_for finds no crew. With
// GT_TMAX_BOSS > 0, a monolith/golem gate may be committed when the team clears it within GT_TMAX_BOSS rounds instead of GT_TMAX,
// but only when no enemy was seen within 8 of it for GT_BOSS_QUIET rounds (opening a gate that then serves the opponent's bag loses:
// a quiet gate means our crew stands at the altar first and banks before they come). Runtime data flag. 0 = use GT_TMAX.
#define GT_TMAX_BOSS 45
#define GT_BOSS_QUIET 30
inline constexpr int GT_TMAX_BOSS_TAB[3] = { 0x47544D42, GT_TMAX_BOSS, GT_BOSS_QUIET }; // slot 0 magic keeps it out of .bss
#define EO_ROUNDS 8
#define EO_FUEL_MIN 30000 // the guard is skipped with less fuel left in the turn
#define HS3_TOP 3 // Shortcut fields: the number of groups, ranked by gems, that get one.
#define HS3_SAVE 10 // Shortcut fields: a launch must save this many steps against walking on from it.
#define HS3_BAND 2 // Shortcut fields: launch tiles whose landing walk is within this of the best one are roots of the field.
#define HS3_WAIT 10 // Shortcut fields: rounds on a launch tile without a dash before that group's shortcut is given up.
#define HS3_RESERVE 35000 // Shortcut fields: fuel to leave after a background build step.
#define HS3_SAFE 25 // Shortcut fields: no shortcut within this many rounds of an enemy seen at the group, or with a foe within 10 of me (0 = off).
#define HT_NEAR 3 // Hole travel bit 4: a spawn crossing's launch (and the body using it) must be within this walk of my spawn.
#define PAW_ON true
bool farm_dom(); // farm's instantiation for the DOM mode.
void threat_seen_dom(const std::vector<vec2>& foes); // threat_seen in DOM mode.
bool dom_commit_free_slot(); // play_turn's free slot; returns true once the DOM commit fires (DOM mode from then on).
#define HC_BONUS_X100 200
#define HC_GEMS 150
#define HC_CMAX_X100 55
#define HC_JOIN 3
#define HC_OPEN_N 3
#define HC_OPEN_SLACK 2
#define HR_RAD 4
#define HR_CMEM_X100 65
#define HR_MAXG 40 // more candidate groups = a field of clusters, not a hoard region (and the pass would cost too much fuel)
#define HR_NB 4 // region groups whose choice bound carries the bonus (the best 4 by plain bound)
#define HR_MAXRG 20 // A region of more groups than this is a field of clusters, not a hoard.
#define HR_FUEL 12000 // a pending decision continues only in a free slot with this much left
#define HR_SLICE 6000 // and works while this much is left
#define HR_LATE_END 60 // an unfinished decision is given up after r60
#define SGR_ROUNDS 60
#define RCL_SC_SKIP 150
// Recall-hop loop guard: the recall-hop travel recall (target_turn) needs a loop guard: an RH recall lands, spawn_crystal_start
// refuses the hop (or the target moves on) and the walk out re-triggers RH at RT_GAP. Runtime data flag RHL_TAB[1], 0 = off, flag
// read first. Bits: 1 LOOPMEM: an RH recall that reached the spawn and left it with no crystal trip started blocks RH recalls and RH
// pricing (compute_travel mode 3) for RHL_SKIP rounds (the crystal-trip failure memory only sees trips that started); 2 HOPTEST: the
// RH recall needs spawn_crystal_start's refusal tests to pass from a spawn tile (the hop saves SC_CRY_MIN over the walk in the
// group's field, and a dasher's known dash route is not as fast); 8 NOHOPMEM: bit 1, but only a hop clears the record (a trip that
// ends unused, e.g. the foe abort, blocks too). A hop-pricing bit in spawn_crystal_travel is not offered: spawn_crystal_travel runs
// inside compute_travel's fuel-counted dash window.
#define RHL_BITS 9
#define RHL_SKIP 150
inline constexpr int RHL_TAB[3] = { 0x52484C31, RHL_BITS, RHL_SKIP };
#define RCG_N 2
#define RCG_R 4
#define RCG_ROUNDS 150
#define SGR_MARGIN_X100 15
int dc_mode(); // The decided state of the DOM commit (3 = hoard mode, 4 = DOM + hoard).
bool farm_hc2(); // farm's instantiation for hoard mode 2.
bool farm_hc3(); // farm's instantiation for hoard mode 3 (DOM + hoard).
void dom_commit_note(float ratio); // This turn's local assess ratio, for the DOM commit.
int lift_flee_blacklist(vec2 at); // Undo threat_seen's blacklists on groups within 5 of a dead foe; returns the number of groups lifted.
int mark_groups_near_kill(vec2 at); // A kill at `at` with no other enemy near: take the nearby groups in the respawn window.
bool lock_hit(bool refresh); // Hit an enemy altar lock within my attack range with a free attack.
bool hit_claimed_camp_in_range(); // PASS_HIT: an unused basic attack hits a living cluster of a harmless own-claimed group in reach
bool bank_first(const std::vector<vec2>& foe_pos, const std::vector<int>& foe_reach); // A carrier near an altar banks before it flees or fights.
// Altar hold: a foe bag I know (seen on a living body) finishes the game. A body that can stop a channel (lock in hand, or a stun on
// a stunnable carrier) stays close enough to the altars that carrier can reach: each calm turn, from current positions, slack =
// carrier's walk to the altar (less rounds since seen) + its channel ticks - my walk to lock range - 1. Slack above ALH_SLACK: free
// to farm. At or below it: walk back, or stand within 2 of the altar. One body per altar, altars by the carrier's soonest finish
// first; visible mates share the job, the strongest body that can make it holds. Never over a bank walk, a winning bag or a paying
// capture (they run first). Runtime data flag ALH_TAB[1] (0 = off). Bit 1: bodies with a stop tool. Bit 2: any body. Bit 4: a known
// bag need not be the whole need: bags of all known foes add up. Bit 8: under FLEE too.
#define ALH_BITS 9
#define ALH_SLACK 2
inline constexpr int ALH_TAB[3] = { 0x414C4831, ALH_BITS, ALH_SLACK };
// Altar pin: ALH frees its holder while slack > ALH_SLACK, but a recall then takes her out of reach for the recall ticks plus the
// walk back from spawn, so a lock holder could leave the only altar while a foe bag finishes. Runtime data flag ALP_TAB[1] (0 =
// off), read first. Bit 1: start_recall refuses while ALH picks me (in time now) as the holder of a finishing foe bag and recall
// ticks + my walk back from spawn to lock range > its eta. Bit 2: handle_low_hp leaves the turn to the rest of the turn (ALH holds)
// while I am that holder with slack <= ALH_SLACK + ALP_M.
#define ALP_BITS 1
#define ALP_M 0
#define ALP_E 30 // ALP_E > 0: pin only while the finishing bag's eta <= ALP_E (a pin held at a long eta blocks a recall that could be safely made)
inline constexpr int ALP_TAB[4] = { 0x414C5031, ALP_BITS, ALP_M, ALP_E };
void altar_hold_note(); // Altar hold: the tributed total at each foe's last sighting.
bool altar_hold_turn(); // Altar hold: true if the tether acted (walked or stood).
bool altar_hold_pinned(bool recall); // ALH picks me to hold an altar and a recall (true) or a retreat (false) would break it
bool end_hold_turn(); // Endgame hold: a lead-flipping bag with a foe near goes home and holds; true if acted (call as END_HOLD_ON && end_hold_turn()).
bool end_hold_blocks_bank(int gems); // Endgame hold: no long tribute start for this bag now.
// WIN_FINISH runtime data flag WIN_FINISH_TAB[1] (0 = off), each bit read first. The need: 1000 - tributed - my bag, and with bit 8
// (or for bit 4) minus my mates' bags that can finish and do not win alone (a Prism carrier's not counted: she keeps it), read from
// the engine once a round. 1 NEED: while 0 < need <= WIN_FINISH_NEED, rate_for prices a gem group by progress toward the win: min(my
// share of its gems, need) in gems, no gold (a group that closes the need is worth exactly the need, so the fastest closing trip has
// the best rate), and siege_try_call / siege_turn start or join no big-group operation that has not started while I have another
// target. 2 HOLD: a winning bag (a Prism carrier's too) whose channel lasts >= WIN_FINISH_TICKS turns and is not safe
// (channel_survives_known_foes over the walk + channel) holds on the spawn, walking home when home is no farther than the altar or
// than the channel lasts, unless a known foe bag ends the game or the round limit is near; mates' needs count my bag, so bit 1 sends
// them to a short finish. 4: want_bank banks any bag (not a Prism carrier's) once my bag and my mates' bags make 1000 (team finish).
// 8 TEAM_NEED: bit 1's need also subtracts my mates' bags (pair it with bit 4, which banks them); without it the need is 1000 -
// tributed - my bag. 16: prism_holds_bank banks her bag when tributed + her bag + my mates' bags (finish_mates_carried: exact in
// sight, PG9 BAGS lower bound out of sight) reach 1000 (pc_hold_why 6), and bank_i never recalls home first for it (the recall-hop
// and recall-bank branches are skipped): the nearest (Prism-safe) altar by walk. PC_OWNER_BANK is untouched otherwise.
#define WIN_FINISH_BITS 16
inline constexpr int WIN_FINISH_TAB[4] = { 0x46494E39, WIN_FINISH_BITS, 60 /* WIN_FINISH_NEED */, 3 /* WIN_FINISH_TICKS */ };
// bank_winning_bag_slow's flip-flop guard (channel_start_ok) covers Prism carriers only. A non-Prism winning bag can be refused at
// the altar by the tribute guard (tribute_start_allowed: WSG, a known foe within WSG_R and not channel_safe), flee one tile, and
// bank_winning_bag walks it back, repeatedly. Runtime data flag WBF_TAB[1] (0 = off), read first; zero work at 0. 1 HOME: once a
// non-Prism winning bag has been refused at the altar by the tribute guard WBF_N times with a turn off the tile between (the
// flip-flop; a refusal the round after a refusal, waiting on the tile, is not counted), each within WBF_GAP rounds of the last
// refusal or guarded turn, bank_winning_bag_slow does not walk it back while tribute_start_allowed still refuses: it takes the bag
// home (go_home: recall if safe, else escape / walk; on the spawn it holds the turn, GameRules.md:151). 2 HYST (with bit 1; alone
// the guard falls back as Prism's does: bank_winning_bag returns false): once the guard has sent the bag off, it walks back only
// when the reason is gone, not at the WSG_R edge: tribute_start_allowed would pass from the altar tile with the current foes
// (nearest known foe > WSG_R + walk, or channel_safe over the walk + channel), or the nearest known foe stays >= WSG_R + 2 for 2
// rounds running, or the race / round limit says bank now. Prism carriers keep the channel_start_ok guard (the PRISM_GREED and
// PC_OWNER_BANK owner rules stay untouched).
#define WBF_BITS 3
inline constexpr int WBF_TAB[4] = { 0x57424631, WBF_BITS, 3 /* WBF_N */, 6 /* WBF_GAP */ };
// DTL: the crew-wait ban (target_turn's 'crew incomplete' drop_target(30)) lifts once the crew it waited for is there. Runtime data
// flag DTL_TAB[1], read first; 0 = off (no mark, no pass). Bit 1 LIFT: each turn (refresh_target, before the choice) a banned group
// whose ban is still that crew-wait ban lifts when the mates I see within DTL_R of its anchor that claim it, plus me, pass the start
// test's estimate() (as crew_here builds the crew). Bit 2 ANY: count every mate I see within DTL_R (claim or not). A ban whose test
// already passes at drop time is never lifted.
#define DTL_BITS 1
inline constexpr int DTL_TAB[3] = { 0x44544C31, DTL_BITS, 7 /* DTL_R */ };
// BLL: a bail's ban (tank_turn's bail, camp_holder_bail, camp_engaged_check's re-entry: drop_target(25)) lifts once its reason has
// lapsed: those sites bench (no ban) when a healthy melee claimant holds the attackers, and the re-entry rule bans only below
// CF_REENTRY_HP. Runtime data flag BLL_TAB[1], read first; 0 = off (no mark, no pass). Bit 1 LIFT: each turn (refresh_target, next
// to DTL's pass) a remembered bail ban lifts when my HP >= BLL_HP %, no visible foe is within 8 of the group's anchor, and a
// claimant mate (melee, HP > 50%, not channelling) stands next to an awake member I see.
#define BLL_BITS 1
inline constexpr int BLL_TAB[3] = { 0x424C4C31, BLL_BITS, 70 /* BLL_HP */ };
#define EBK_FIRE(b) ((void)0) // diag copies record a firing of bit b
int mates_landing_by(int t_done); // EBK bits 1/16: my mates' gems that land within t_done rounds (0 at flag 0)
bool bag_wins_with_mates(int gems); // EBK: W.tributed_us + gems (+ bits 1/16: mates_landing_by by my walk + channel) >= 1000; the plain sum at flag 0
bool cancel_recall_for_winning_bag(int left); // WBR2 bit 1: cancel a kept recall whose bag now wins nearer the altar
bool bank_winning_bag(); // My bag wins the game and a tribute tile is within the win distance: bank now; true if acted.
int finish_rounds(vec2* anchor, float* camp_in); // Rounds to finish my engaged target group if it pays soon, else -1.
bool target_pays_within(int max_rounds); // True if my running capture pays, or my engaged target group finishes, within max_rounds (combat.h).
int home_dist();                // walking distance home (estimate)
bool start_prestep(); // One greedy step toward the start goal in a turn that ends before turn() (raw SDK).
bool start_step(); // End-of-turn cheap step for a body that did nothing near our spawn in the first rounds.
int wait_cap(); // the map's respawn-wait cap (rounds)
const std::vector<GroupMem>& memory();
int csx_recall_t(); // CSX bit 128: measured rounds from a recall's decision to acting on spawn
bool camp_known_dead(int ci); // CSX: camp ci is known dead (seen: no camp on its tile; unseen: fogged_camp_group_near_landing's memory test)
// WARD: team intelligence (intel.cc): an enemy seen near a group, a group captured at a round, a group cleared by enemies.
void intel_enemy(int gi, int round);
void intel_taken(int gi, int capture_round);
void intel_cleared(int gi, int round);

void buy_crystal(); // CRYSTAL: buy a teleport crystal on our spawn when walled-off groups exist
bool crystal_use_ready(float* camp_dmg); // CRX (combat.h): I carry a crystal; *camp_dmg = awake camps' damage on me per turn
bool use_crystal_consumable(vec2 t, bool* hidden); // reserve t; *hidden: an unseen occupant refused it
void spawn_crystal_prebuy(); // On our spawn or dead, on a map with a crystal route: buy one before the shop.
void recall_hop_prebuy(); // Recall hop bit 16: on the spawn, a big-saving route buys the crystal before the shop.
bool recall_hop_early(); // Recall hop bit 1: the route precompute runs before the intel and ward analyses.
void spawn_crystal_background(long reserve); // The spawn crystal route precompute in spare fuel (resumable).
void crystal_plan_background(); // Plans crystal routes in spare fuel.
#define WBK_TGT true
#define WBK_REACH 6     // a spell's range 4 + one dash
#define WBK_MARGIN 2
#define WBK_SPD_X100 125 // a walk a round + a dash every 8
#define WBT_BAG 200
// CNW: group news that the team can use. The ward-news switch is 0, so intel_cleared updates nothing: a far body would keep walking
// to a group a mate already cleared until TAKEN comes at payment. Bit 1: a body at its target group that sees the last camp dead
// with no foe near posts EV_CLEARED at once; a reader with a mate's claim on the subject (news under CNW_AGE rounds old) treats it
// as ours: no foe report, group marked as respawning (the usual arrival-cover and rate_for rules then decide), except a body busy
// with it and a carrier within PC_ROUTE_R. Runtime data flag CNW_TAB[1]; flag read first. 0 = off.
#define CNW_BITS 1
#define CNW_AGE 4
inline constexpr int CNW_TAB[3] = { 0x434E5731, CNW_BITS, CNW_AGE };
bool mate_claims_group_recently(int gi, int round); // fresh news about a group a mate claims: an EV_CLEARED about it is our own clear
bool group_is_ours_to_post(int gi); // the same for the poster: I or a mate claim it
// OEG: the opening crew rule makes a non-tank member wait for the tank (or 3 rounds) before an own-side elk group
// (opening_elk_group). Bit 1: a non-tank member at >= 90% HP starts the group itself (as the waited >= 3 self-tank start) when the
// tank's walk to the group is <= 3 rounds: an elk hits 60 a round and moves to the tank once it is nearer. Bit 2: a member waiting
// for the tank there steps down the group field to the edge of the camps' reach instead of standing inside stage_near's ring. Bit 4:
// bit 1's rule in the opening only (round <= OEG_OPEN_R). Runtime data flag OEG_TAB[1], read first; 0 = off.
#define OEG_BITS 4
#define OEG_OPEN_R 30
inline constexpr int OEG_TAB[3] = { 0x4F454731, OEG_BITS, OEG_OPEN_R };
// CMP: CAMP entries in PACK's spare bits, K = CMP_K (2) if it fits, else 1, else none. Entry = group+1 (bit_width(ng)) | log
// countdown (4 bits, 3 if short) | stamp (round & 3). Bit 1: writer (econ observe end, alive): a group I hold a respawn timer for
// from my own sight of the dead group, whatever I target now; one entry per turn, when no post yet gives the team an estimate as
// good as a new one would; never over an entry first seen < 2 rounds ago. Reader (camp_news_read, every turn incl. dead, after
// comms::read; only entries whose bits moved): a new entry sets the group respawning at stamp-round + bucket lower edge, unless I
// work it, my own sight is as new, or my own timer is inside the bucket. Bit 2 timing consumer ('alive at my arrival'): target
// choice charges the wait only before respawn - 1, and an entry that puts my target's respawn past my arrival + 1 makes the target
// choice due this turn. Bit 8 EXACT: the entry is group+1 | (R / 2) mod 128 with no stamp (absolute R never goes stale); the writer
// sends each item once; readers take the one R in [now-100, now+155] as 'no earlier than'. Bit 4 unused. Runtime data flag
// CMP_TAB[1], read first; 0 = off.
#define CMP_BITS 1
#define CMP_K 2
inline constexpr int CMP_TAB[3] = { 0x434D5031, CMP_BITS, CMP_K };
void camp_news_read(); // CMP bit 1 reader: brain turn() right after comms::read(), also while dead
bool camp_news_due_take(); // CMP bit 2: a new entry made my target choice due (cleared on read)
void team_mem_post_legacy_event(int subject, int type, int round); // TM2 bit 16: comms::write_event's events go out on the channel
inline int bhf_lp = 2; // BHF bit 128: the last team_mem_post_legacy_event: 0 = not posted (dropped/blocked), 1 = posted; intel sets 2 before a write
int team_mem_claim_state(int g, bool engaged); // TM2 bit 8: my claim's bucket (heading: ETA; engaged: forecast rounds to clear)
bool tm2_channel_on(); // the channel exists on this map
// CXF: crystal trip fixes. Runtime data flag CXF_TAB[1] (0 = off; every hook reads it first), bits: 1: rate_for would price a live
// crystal trip's own group by my full walk once a mate joined it (crew > 1, spawn_crystal_crew_trav), though I hop, so a
// claims-moved re-rating could switch the trip partway through the walk. The trip's group is priced at min(walk, max(my hop ETA, the
// slowest claimant mate's ETA)). 2: spawn_crystal_step aborted the hop when a foe was within 4 of the planned landing (or of me),
// with no other landing tried, and blocked hops 10/30 rounds. Foe-near landings are skipped and the best foe-free landing within 3
// that still saves SC_CRY_MIN is taken; with none, the trip holds at the launch and re-checks each turn while the hop still saves
// SC_CRY_MIN after the wait (at most CXF_HOLD holds), then the abort.
#define CXF_BITS 3
#define CXF_HOLD 3
inline constexpr int CXF_TAB[3] = { 0x43584631, CXF_BITS, CXF_HOLD };

} // namespace nova::econ
namespace nova {
struct Body;
// Tribute records and gates (econ_tribute_gates.cc); brain's turn writes the records.
extern int td_cancel_round; // Round of my last doomed-tribute cancel.
extern int td_cancel_left; // Ticks left at the last doomed cancel.
bool new_tribute_blocked(); // True while a new tribute would be doomed the same way.
extern int b781_trib_start; // Round of my last tribute start.
extern int td_lost_round; // First own turn after my tribute channel ended without paying (any cause).
extern int b781_ec_round; // First own turn after the enemy ended my tribute channel.
extern vec2 b781_ec_pos; // Where I stood then.
void note_channel_ender_foes(); // Notes the enemy champions near me after the enemy ended my channel.
}
namespace nova::econ {
vec2 fight_cell_tile(int cell); // FL (comms.h): a 6x6 FIGHT cell's centre
int fl_cell_of(vec2 p); // FL: the 6x6 FIGHT cell of a tile
bool fight_cell_post(int call); // FL bit 2: post FIGHT cell(my tile) x call (0 rally, 1 commit, 2 hold, 3 retreat)
extern int fl_n_post[4], fl_n_drop;           // FL: firing counts
// HPL: with upgrades the heal line can fall. Runtime data flag HPL_TAB[1], read first; 0 = off. Bit 1 LINE (wants_heal): the fixed
// near / far line L splits into a camp part and a foe part. Camp hits are flat, so the camp part is real HP: L x share / G, G = max
// HP / kit HP. Foe damage grows, so the foe part is L x (1 - share) x (1 + k (D - 1)), D = mean foe power over kit power from the SG
// table (last seen by this body, carried forward by siege_strength_growth; the siege_strength_growth curve alone on a map with no SG table), capped at DCAP.
// The line stays in [floor, L], so a body with no upgrades keeps L. Near and far have their own share, k and floor.
#define HPL_BITS 0
#define HPL_CF 0   // far: camp share of the line, %
#define HPL_CN 0   // near: camp share of the line, %
#define HPL_KF 25  // far: k x 100
#define HPL_KN 25  // near: k x 100
#define HPL_MINF 30 // far: lowest line, %
#define HPL_MINN 50 // near: lowest line, %
#define HPL_DCAP 300 // D cap x 100
// Bit 2 DASH: a body whose kit has a dash takes points off the line, more while the dash is ready (own cooldown, W.cd). Own kit and
// cooldown only. Same floors as bit 1, and it reads alone or on top of bit 1.
#define HPL_DRF 0 // far: points off, dash ready
#define HPL_DCF 0 // far: points off, dash cooling
#define HPL_DRN 0 // near: points off, dash ready
#define HPL_DCN 0 // near: points off, dash cooling
// Bit 4 REL (relative to max health; replaces bit 1, same share, k and floors): the line turns around L + up, so a body at base max
// HP sits up points above L and an upgraded body falls below L. Up is sized so the mean recall HP stays about level.
#define HPL_UF 0 // far: points up at base max HP
#define HPL_UN 0 // near: points up at base max HP
inline constexpr int HPL_TAB[15] = { 0x48504C31, HPL_BITS, HPL_CF, HPL_CN, HPL_KF, HPL_KN, HPL_MINF, HPL_MINN, HPL_DCAP, HPL_DRF, HPL_DCF, HPL_DRN, HPL_DCN, HPL_UF, HPL_UN };
inline constexpr int HPL_BIT_REL = 4;
// QKW: runtime data flag QKW_TAB[1], read first; 0 = off. QUIET = alive, round >= QK_QTR and nobody on the team saw a foe (own/ward
// sight, mates' enemy news, last-seen reports) nor took an unseen hit for QK_QTR rounds. Q1 (only while quiet; never
// fight/flee/reaction code): bit 1 rate_for contest slope x QK_CONT/100 and no seen-foe penalty; bit 2 no lone-trip guards
// (CREW_GUARD, the deep-pair guard); bit 4 crew budget floor QK_FLOOR % of max HP (22 otherwise); bit 8 bank bar x QK_BANK/100; bit
// 16 heal line - QK_HEALD/100 (>= .35). Q2 KILL WINDOW (foe deaths are visible map-wide): bit 32 rate_for contest slope and seen
// penalty scale with the share of foes that can stand on the group (respawn 60 + walk from their spawn) before my job ends, groups
// with contest > .40; bit 64 bank bar x QK_KWB/100 while a foe is dead and the first return is after my bank (walk + channel). M1:
// bit 128 last-seen on the TM2 channel (64 codes after TM2's: (R/2) mod 64, absolute), posted at priority 15 (below camp news) only
// when the team value is >= QK_QTR - QK_GAP rounds old and my own sighting/unseen hit is fresh.
#define QKW_BITS 8
#define QK_QTR 15
#define QK_CONT 0
#define QK_BANK 150
#define QK_HEALD 20
#define QK_FLOOR 12
#define QK_KWB 60
#define QK_GAP 5
inline constexpr int QKW_TAB[9] = { 0x514B5731, QKW_BITS, QK_QTR, QK_CONT, QK_BANK, QK_HEALD, QK_FLOOR, QK_KWB, QK_GAP }; // QKW quiet mode: while no foe has been seen by anyone
// DLT: runtime data flag DLT_TAB[1], read first; 0 = off. Bit 1: rate_for rejects (also for my current target) a lone trip (crew 1,
// no claimant, no crew ally near) to a group deep in their half (contest > DLT_CONT/100) whose rate is below DLT_FLOOR/1000, unless
// two foes are down (foes_down_count) or every living foe is accounted for away from it (opportunity_factor's FREE test). Bit 2: in
// the opening simulation an attacker-free gem group in our half or the centre (contest <= DLT_OCONT/100) takes the spawn pack factor
// (opening_pack_factor) at any distance, like a group within 8 of home.
#define DLT_BITS 1
#define DLT_FLOOR 800
#define DLT_CONT 60
#define DLT_OCONT 55
inline constexpr int DLT_TAB[6] = { 0x444C5431, DLT_BITS, DLT_FLOOR, DLT_CONT, DLT_OCONT, 0x31544C44 };
extern bool qk_wasq; // I was quiet at the end of last round (before this turn's sight)
void team_quiet_track();  // brain turn(), after combat::observe (also while dead)
bool team_quiet();  // cached per round
int qk_last();    // newest team sighting / unseen hit round known to me
extern int qk_n_post, qk_n_read, qk_n_drop; // M1 counts
extern bool bh64_lp_drop; // Help-fix bit 2: the last team_mem_post_legacy_event found no entry, so its post was dropped.
extern int t2_lp_res; // the last team_mem_post_legacy_event: -1 none, 0 dropped (no entry), 1 posted, 2 held by a cap rule
extern int tmf_n[8]; // TMF firing counts: 0 queue extra events, 1 HELP image kept, 2 drops kept, 3 bumped seen, 4 resent ok, 5 resend dropped
// MUL bit 4 COMING (multipliers.h): my last sighting of mate slot s (GRW grw_ls, else UPG upg_ls): Str, Foc, max HP; died = seen
// dead since (it may have shopped). False when never seen.
bool mul_mate_ls(int s, float& str, float& foc, float& maxhp, bool& died);
} // namespace nova::econ

namespace nova::econ::twin_altar
{
// True: walked toward a free twin altar this turn (the caller returns). Caller read the flag.
bool walk_to_free_twin_altar(vec2 me);
} // namespace nova::econ::twin_altar

namespace nova::econ::threat_checks
{
inline int cex_round = -1000; // the round sense() found camp-excess damage
bool unexplained_hp_loss(float loss, int rounds); // loss beyond every awake camp in reach, no visible foe to explain it
void low_hp_flee_zones(const ::nova::combat::Assessment& a, std::vector<::nova::mv::Threat>& z); // Adds the foes' reaches to the flee zones, widened by a mate-reported foe's veto reach and by two foe turns' walk.
} // namespace nova::econ::threat_checks

namespace nova::econ::crew_bypass
{
int count();                  // free_near's extra: the bypass-eligible claimed mates near me
bool ok(int s, int gi, int cg); // mate s (claim cg) may join my crew for group gi
void fired_add();               // firecount's entry counter: ok() said yes
} // namespace nova::econ::crew_bypass

// Crew-pooled bail from a camp. Flag CREW_BAIL_POOL_BITS (common.h); hooks in crew_mates_in_reach, tank_turn and camp_holder_bail.
#include <vector>
namespace nova::econ::crew_bail
{
// True: skip my own camp bail this turn (the crew holds, and I take no hits now or can step out next turn).
bool skip(int gi, const std::vector<mv::Threat>& th, float hp_left, float dps, float eff, int steps);
} // namespace nova::econ::crew_bail

namespace nova::combat
{
struct Assessment;
}
namespace nova::econ::capture_end
{
// bit 1: true if the turn was used contesting a game-ending capture. keep = brain's keep_bar(). Caller read the flag.
bool end_turn(const ::nova::combat::Assessment& a, float keep);
// bit 2: a group under CC_GEMS passes contest_capture_turn's gem gate at CCE_GEMS. Caller read the flag.
bool low_ok(int gems);
} // namespace nova::econ::capture_end

// camp crews waiting on a heal (CMQ). Flag word CMQ, 0 = off. Bit 32 BLH: a tank-bail ban (drop_target(25) + bail_ban_remember) also
// lifts once I am healed (HP >= BLL_TAB[2] %) and no foe was seen within 8 of the group for 15 rounds; bail_ban_lapsed alone needs a
// healthy melee claimant I can see on an awake member, which never holds after a heal recall (the crew left), so the body would be
// banned 25 rounds from its own half-done group. Hook: bail_ban_lift_lapsed. Bit 128 LSH: last-seen health for hidden members
// (lsh_hp). Hook: observe. Bit 4 CRW: the crew-pooled bail with attacker deaths (the crew-hold function below). Hooks: tank_turn and
// camp_holder_bail, beside the crew-pooled bail.
#include <vector>
namespace nova::econ::camp_crew
{
// BLH: the bail ban on group gi may lift now (caller read the flag).
bool heal_lift(int gi);
} // namespace nova::econ::camp_crew

namespace nova::econ::emblem_order
{
void passive_first(std::vector<cambc::item_type>& build, const decltype(cambc::self().item_count())& counts);
} // namespace nova::econ::emblem_order

namespace nova::econ::fight_help
{
bool fight_call(const ::nova::combat::Assessment& a); // CALL: this FIGHT turn calls idle mates
void trip_call(); // CALL: a HELP went out (firing)
bool join_worth(vec2 at); // JOIN: engaged on a camp, answer the call centred at `at`
bool peel_vetoes_target(float worst); // PEEL: true = no peel FIGHT this turn
} // namespace nova::econ::fight_help

namespace nova::econ::carry_recall
{
// true: the visible foes cannot deal RCD_PCT% of my health in their n turns before my recall lands
bool ok(int n);
void fired_rec(); // the RCD recall was started (firecount's entry counter)
} // namespace nova::econ::carry_recall

// keep or cancel a winning tribute channel (econ_bank_win, WCK). Flag WCK_BITS, 0 = off. A winning-bag channel at or above
// PC_WIN_KEEP_HP has no lethal check of its own; this adds a short one: foe_damage_over_ticks(WKH_AGE, WCK_TURNS) >= WKH_PCT % of HP
// + shield (the known foes' burst + dps over the next 2 foe turns; not the channel's ticks: the full horizon blocks most starts).
// Bits: 1 KEEP: channel_doomed: the channel_doom_exempt keep of a winning channel at >= the HP line yields when the 2-turn test
// trips. 2 START: channel_start_ok WIN_START: the same test refuses the start. 4 STEP: the turn of a bit-1 cancel takes stance FLEE,
// and flee's zones take every foe's two-turn reach (foe_two_turn_reach_after_turn_count). 8 ESCORT: WIN_START at >= the line opens
// despite winning_tribute_start_blocked when the 2-turn test passes and every visible foe within PC_CHAN_R has a mate at >=
// WCK_ESC_PCT % HP within WCK_ESC_R of it. Unchanged: non-winning bags, below-the-line WKH, the PRISM_GREED / PC_OWNER_BANK /
// CI_SAFE owner rules, stuns.
#include <vector>
namespace nova::econ::win_channel
{
inline int cancel_round = -1000; // KEEP: the round bit 1 cancelled my channel
bool keep_cancel(int gems); // KEEP: true = cancel the kept winning channel (callers: only after channel_doom_exempt kept it)
bool start_refuse(int gems); // START: true = refuse a winning start at or above the HP line
int start_gate(int gems); // START/ESCORT: -1 refuse, 1 open, 0 leave channel_start_ok as it was
void force_flee(::nova::combat::Assessment& a); // STEP: stance FLEE on a KEEP cancel turn
void widen(const ::nova::combat::Assessment& a, std::vector<::nova::mv::Threat>& z); // STEP: two-turn zones on that turn
} // namespace nova::econ::win_channel

namespace nova::econ::win_bag_flee
{
inline constexpr int WFF_WIN = 6;    // the window, turns
inline constexpr int WFF_FLEE_N = 3; // FLEE turns in it
inline int wff_last = -100;          // the round of the last note
inline unsigned wff_mask = 0; // bit k: FLEE stance k rounds before wff_last
inline bool wff_flee = false; // this turn's stance is FLEE
// Each turn before early_stages: the FLEE history; a channel (a tribute started) clears it.
inline void note(bool flee)
{
	const int d = ::nova::W.round - wff_last;
	wff_mask = (d < 0 || d >= 32) ? 0u : (wff_mask << d);
	if (::nova::W.me.channeling())
		wff_mask = 0u;
	else if (flee)
		wff_mask |= 1u;
	wff_last = ::nova::W.round;
	wff_flee = flee;
}
inline int wff_g2 = -100; // bit 2: the round the gate turned a FIGHT into FLEE
// Bit 2: called by assess() for a new FIGHT (no fight last round) without kill_now of a winning bag; true = the stance becomes FLEE
// (only when the foes' two-turn burst reaches my effective HP: gate_burst).
bool gate();
// The episode (bit 1) or the gate's turn (bit 2): noted this turn, WFF_FLEE_N FLEE turns in the last WFF_WIN, not channeling, off
// the spawn.
inline bool live()
{
	return wff_last == ::nova::W.round && __builtin_popcount(wff_mask & ((1u << WFF_WIN) - 1u)) >= WFF_FLEE_N && !::nova::W.me.channeling() && !::nova::W.on_spawn;
}
// bank_winning_bag's answer for a winning bag in the episode: true = acted (recall or the walk home), false = the flee takes the turn.
bool act();
// The guards (game end, on a tribute tile off FLEE); true = the episode takes bank_winning_bag's turn.
bool own(int gems);
// Bit 4 STAKE: adds (the stake rise - base_e) to engage and (the stake rise - base_f) to flee: combat's own rise (base_e, base_f)
// then makes the stake rise.
void stake_bars(int bag, float base_e, float base_f, float& engage, float& flee);
} // namespace nova::econ::win_bag_flee
