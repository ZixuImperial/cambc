#pragma once
// champ_prism.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Prism
// (GameRules.md:556-586). Ranged 3, HP 700 +65, Str 35 +2.5, Focus 90 +8. PASSIVE: +1.5 Focus per carried gem, lost when she
// tributes or loses them; the engine includes it in her current Focus. Code: Kit::gem_focus through the prism_layer hooks;
// prism::carry_on is the carrier plan built on it. Slot 0: 1.5 x Focus and a one-round stun, range 4, excludes walking. Slot 1: area
// 1 x Focus, radius 1, range 4, excludes walking. OWNER RULES, kept: PRISM_GREED, PC_OWNER_BANK (she keeps her bag), CI_SAFE.
#define PC_WAIT_BANK 0 // target_turn: the bank while the target camp respawns
#define PC_RING_BANK 0 // want_bank: bank at the ring gap on altar-ring maps
#define PC_DASH_BANK 0 // want_bank: the dash bank when no altar is walkable
#define PC_CHAN_R 8 // no known enemy champion within this many tiles to open or keep a channel
// PXC (b1838, Prism Planner spec_pxc_1110 bit 8; RC C169 VERIFIED, bug bar). Runtime data flag, read first; 0 = v746. Bit 8: channel_doomed
// keeps her tribute when no proximity cancel can buy anything: nearest known foe >= PXC_NEAR, every assessed foe outside its one-turn
// reach (+1 with two turns before her next, +1 more if remembered; a remembered foe counts as two-turn), HP >= PXC_HP %, and the kill
// test (win_channel::keep_cancel) false. Bits 1/2/4 stay closed (never shipped).
#define PXC_BITS 24
#define PXC_NEAR 6
// v750 PXC: PXC8 gate uses the two-turn reach (PXC16)
#define PXC_HP 60
inline constexpr int PXC_TAB[4] = { 0x50584338, PXC_BITS, PXC_NEAR, PXC_HP }; // slot 0 magic keeps it out of .bss
// v748 PXC bit 16 (RC C178, b1838): with bit 8, a visible foe's gate is geom::foe_two_turn_reach (its walk, dash and casts over the turns
// before her next, a dash that comes off cooldown on its 2nd turn included; -1 = one turn: its reach); remembered foes keep reach + 2.
#define PC_CHAN_BAG 30 // channels of this many gems or more (3+ turns)
#define PC_DOOM_LEFT 2 // channel_doomed tests a channel only while it has this many ticks left or more
// Channel margin: the threat bank opened a bank when the nearest known foe was beyond walk + chan + PTB_SLACK, but channel_doomed
// cancels at a foe within PC_CHAN_R while PC_DOOM_LEFT+ ticks are left. A foe walking straight in from walk + chan + 3..6 would make
// her cancel the channel she had just opened. 1: prism_threat_bank_applies also needs channel_not_doomed(), channel_doomed's own
// test (same keep arms, PC_CHAN_R, PC_DOOM_LEFT) over the walk and the tested ticks. The cancel and keep arms are unchanged. Runtime
// data flag: 0 and 1 compile the same code.
#define CC_WAIT 8
#define CC_FOE 8
#define PC_WIN_KEEP_HP 60 // her HP, in percent of her max, needed to keep a winning channel with an enemy near
// Winning-channel keep: a winning Prism channel below the HP line is not cancelled by default. Runtime data flag WKH_TAB[1]; slot 2
// is the PC_WIN_KEEP_HP line. Bit 1: for a winning bag (tributed_us + gems >= 1000) below the HP line, channel_doom_exempt
// (channel_doomed, channel_not_doomed) and channel_start_ok's winning-start keep (start) the channel unless (a) the known foes'
// burst + dps over ticks + 1 foe turns (the starting team swaps; combat::foe_damage_over_ticks, WKH_AGE-round memory, dash
// allowance) reaches WKH_PCT % of her HP + shield. Bit 2: also not when (b) a foe seen within WKH_AGE rounds holds a bag that wins
// for them and its earliest bank (its channel's ticks left, else walk - 1 + our visible lock's hits + ceil(bag / 10)) lands no later
// than ours. At or above the line the old rule applies: a kill test there cut most winning starts. A lock or stun keeps the bag, so
// it is no reason. tribute_doomed, non-winning bags and the owner Prism rules (greed, keeping her bag, the safe pair) are unchanged.
#define WKH_BITS 3
#define WKH_AGE 3
#define WKH_PCT 100
inline constexpr int WKH_TAB[5] = { 0x574B4831, WKH_BITS, PC_WIN_KEEP_HP, WKH_AGE, WKH_PCT }; // a winning Prism channel below 60% HP is kept
// FSB (b1808, owner OK 10 Nov: Prism start/keep fixes, bars decide). Runtime data flag FSB_TAB[1], read first; 0 = v690. A foe bag read
// rounds ago may already be tributed out of my sight. Bit 1 FOE2: foe_banks_winning_bag_first skips a bag once tributed_them has risen by
// at least that bag since the round of the read. Bit 2 FOE4: foe_finish_eta's BAGS term, the same drop.
// v693 FSB: 4 fixes be2b8f,fsb4,qms1,prb4f
#define FSB_BITS 3
inline constexpr int FSB_TAB[2] = { 0x46534231, FSB_BITS }; // slot 0 magic keeps it out of .bss
// FSB2 (b1823, RCP4 P2, Rule Checker Pass 4 FSA1/FSA2). Runtime data flag FSB2_TAB[1], read first; 0 = v699. fsb_banked's test (the
// foe tribute rise since a bag's read covers every unseen foe bag). Bit 1 FSA1: testing an OLD bag (read > RFE_AGE rounds ago, a PBQ
// keep), the unseen sum is that bag plus the bags read within RFE_AGE rounds; a young tested bag keeps the full sum (C32 review).
// Bit 2 FSA2: the rise loses each other living foe's bag drop between the tested bag's read and that foe's later read (a foe seen
// banking raised the total; that rise is not the unseen bag's); a foe that died after its found read is skipped (GR:220, C32 FSD1).
// FSB2_LOOK: rounds back from the tested read for a foe's bag (C32 FSW1: narrow).
#define FSB2_BITS 1
// v708 FSB2: baked at its shipped value
#define FSB2_LOOK 12
inline constexpr int FSB2_TAB[3] = { 0x46534232, FSB2_BITS, FSB2_LOOK }; // slot 0 magic keeps it out of .bss
#define FSB2_ON(b) ((FSB2_TAB[1] & (b)) != 0)
// QBR (b1808, Prism carrier briefing, owner OK 10 Nov). Runtime data flag QBR_TAB[1], read first; 0 = v690. Bit 1: prism_holds_bank's
// second why-1 test is an else-if of the first (why 2/5/6 no longer overwrite a why 1), and pbk_walk_she_takes reads this call's
// pc_hold_why (0 so far), not the last call's. Bit 2: finish_mates_carried counts an unseen mate's last read bag for QBR_AGE rounds
// (dropped once tributed_us rose by it, or the mate died). Bit 4: channel_not_doomed's kill test counts foe damage over the channel
// ticks only (she walks first; the walk's foe approach is in the distance test).
#define QBR_BITS 2
// v691 QBR: team-win bank counts unseen mates last bag
#define QBR_AGE 60
inline constexpr int QBR_TAB[3] = { 0x51425231, QBR_BITS, QBR_AGE }; // slot 0 magic keeps it out of .bss
// EAP (b1932, spec_eap_1111): end-game approach. APPROACH = she is the largest carrier, bag >= EAP_BAG, WIN - EAP_K <= tributed + bag
// + finish_mates_carried < WIN. Bit 2 NEAR RELEASE: prism_holds_bank's why 7 (bank now) at d <= EAP_D with no foe known within 8.
// Read EAP_ON first.
#define EAP_BITS 2
#define EAP_K 150
#define EAP_BAG 150
// v765 EAP: EAP2 Prism banks near altar before the line
#define EAP_D 6
inline constexpr int EAP_TAB[5] = { 0x45415031, EAP_BITS, EAP_K, EAP_BAG, EAP_D };
// QMS (b1808, FSB-TEAM on qbr2). Runtime data flag QMS_TAB[1], read first; 0 = v692. Bit 1: an unseen mate's last bag is dropped only
// when tributed_us has risen since its read by the sum of every unseen mate's stored bag (the rise is team-wide).
#define QMS_BITS 1
// FST (b1808, FSB-TEAM adaptation of FSB). Runtime data flag FST_TAB[1], read first; 0 = v692. Bit 1: fsb_banked's team-wide tributed_them
// rise must cover the sum of every carried foe bag not read this round, not the one bag tested.
// v693 FST: 4 fixes be2b8f,fsb4,qms1,prb4f
#define FST_BITS 1
inline constexpr int FST_TAB[2] = { 0x46535431, FST_BITS }; // slot 0 magic keeps it out of .bss
// v693 QMS: 4 fixes be2b8f,fsb4,qms1,prb4f
inline constexpr int QMS_TAB[2] = { 0x514D5331, QMS_BITS }; // slot 0 magic keeps it out of .bss
// QMD (b1808, QBR2-AGE from b1809). Runtime data flag QMD_TAB[1], read first; 0 = v693. Bit 1: a mate read dead drops its stored bag (the
// bag was lost), so it no longer counts after the respawn within QBR_AGE. Bit 2 (FST-SEEN twin): a bag read this round counts as carried
// (qms_unseen_sum leaves it out, so the rise test read it as banked when no other mate's bag was unseen).
// v695 QMD: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define QMD_BITS 1
inline constexpr int QMD_TAB[2] = { 0x514D4431, QMD_BITS }; // slot 0 magic keeps it out of .bss
#define PC_KNOWN_AGE 3 // rounds a remembered enemy (combat memory) counts as known near; its distance shrinks 1 a round
// 2000": no race-deadline bank (it fired whether or not her bank wins; a winning bag already banks in want_bank)
#define PC_LATE 40 // near round 2000: walk + 2 channels + this many rounds
#define PC_RACE_T 120 // ... or would reach 1000 at its recent rate within the bank time + this many rounds
#define RR_SLACK 40
#define PBL_AGE 100
// BLT (b2440; Deep spec_blt_1112 in RC C687's final form). Runtime data flag BLT_TAB[1], read first; 0 = v911. PRW bit 8 (live) already
// adds our rate x (walk + channel) to why 6, so the projection is shipped; bit 1 is the C687 latch: once why 6 says 'bank' with a bag
// >= BLT_BAG, a later call that finds no reason keeps why 6 while her bag is still >= the latched bag, within PBL_AGE rounds (a one-turn
// dip of the carried-mates term must not end the bank trip: Path Finding, 00great_wall r623).
#define BLT_BITS 1
#define BLT_BAG 150
inline const volatile int BLT_TAB[3] = { 0x424C5431, BLT_BITS, BLT_BAG }; // slot 0 magic keeps it out of .bss
#define BLT_ON(b) ((BLT_TAB[1] & (b)) != 0)
// b2362 PRD PRISM RACE DEPOSIT (Planner, after the PGR end-hoard witnesses: live's bank logic held 545-914 bags while the foe finished).
// Runtime data flag PRD_TAB[1], read first; 0 = v868. Bit 1: in prism_holds_bank (want_bank's own-rule path; not while capturing), with no
// other reason, her bag goes in (why 8) when the foe nears the win: tributed_them >= PRD_T, or tributed_them + the foe bags read in the last
// PRD_AGE rounds (team table) >= PRD_SUM; and her bag >= PRD_BAG, she is not channelling, tributed_us + bag < WIN_TRIBUTE (why 6 has it),
// the bank walk <= PRD_W, and no seen / remembered foe can stop the channel in walk + channel ticks (PKR's stop test,
// combat::tribute_stop_possible, live since v874; RC C1129); the carried list skips bags seen banked since the read (fsb_banked, RC C1129).
// A channel of more than PRD_LONG ticks waits while a stun-capable foe with its stun ready is seen within PRD_STUN_R (one cooldown).
#define PRD_BITS 1
// EAF (b2362, RC X897 PEAF1; bug bar): bank reason 7 (EAP APPROACH) checks only foes in sight or ward (eap_no_foe8); bit 1 also needs no
// enemy champion KNOWN within PC_CHAN_R (nearest_known_enemy: visible, ward, combat memory), as channel_start_ok does. 0 = v882.
// v896 EAF: 7 verified bug fixes (TTCX TDP EAF OLK RFV NTG CHO)
#define EAF_BITS 1
inline constexpr int EAF_TAB[2] = { 0x45414631, EAF_BITS }; // slot 0 magic keeps it out of .bss
#define PRD_T 700
#define PRD_SUM 900
#define PRD_AGE 4
#define PRD_BAG 50
#define PRD_W 15
#define PRD_LONG 20
// v882 PRD: PRD rebase on v876 (live stop test)
#define PRD_STUN_R 10
inline constexpr int PRD_TAB[9] = { 0x50524431, PRD_BITS, PRD_T, PRD_SUM, PRD_AGE, PRD_BAG, PRD_W, PRD_LONG, PRD_STUN_R }; // slot 0 magic keeps it out of .bss
#define RACE_DENY 0
#define PG_GOLD_PER_GEM 20
#define PCSF_T 20
#define PCSF_MATE 6
#define PCSF_R 12
#define PCSF_AGE 5
#define RD_BAG 60
#define RD_AGE 10
#define PC_CAP_TMIN 8 // the bag cap's channel turns are clamped to [PC_CAP_TMIN, PC_CAP_TMAX]
#define PC_CAP_TMAX 40
// Mates take gems near her (29 of 31 big mate captures within 12 had her at cap), so her capture-routing cap is lifted (greed rule:
// cap_of_prism; capture ranking, prism_route_to_plan_groups, mate_waits_for_prism_capture).
#define PC_CAP_DEFAULT 250 // the bag cap without a plan
#define PC_ROUTE_R 12 // she joins / mates wait for her within this Chebyshev distance of the group anchor
#define PC_ROUTE_WAIT 10 // a mate waits at most this many rounds off a cleared plan group
#define PC_ROUTE_GEMS 20 // plan groups hold this many gems or more
#define PZD_GG_X100 30
#define PZD_HEAVY_PCT 90
#define PZ_POCKET_W 60
#define PZ_POCKET_MIN 100
#define PZ_GOLDW_PCT 30
#define PZ_CLU_PCT 150
#define PZ_HP_SHARDS 5
#define PG_BAG 60
#define PG_FAR 5
#define PG_NEAR 2
// PGL (b2388, Path Finding spec_pgl_1113): the Prism guard walk (team_stage) had no threat test and pulled working bodies off trips.
// Runtime data flag PGL_TAB[1], read first; 0 = v855. Bits: 1 a guard post only with a foe known (my sight or ward, team_table src 1/2,
// age <= PGL_AGE) within PGL_R of her; 2 no guard role for a body holding a claimed target (mates with a claimed group are passed over);
// 4 no guard while she is within PG_FAR of our spawn or home altar with no foe known within PGL_HOME_R. No bit acts at bag >= PGL_HOLD_BAG.
// v891 PGL: PGL no guard pull off claimed trips / at home
#define PGL_BITS 6
inline constexpr int PGL_TAB[2] = { 0x50474C31, PGL_BITS };
#define PGL_AGE 3
#define PGL_HOME_R 10
#define PGL_HOLD_BAG 400 // no PGL bit acts at her bag >= this (Prism Planner: PGR's altgrp1 hold at 400+ keeps its mate)
#define PG_R 10
#define PG_THREAT 5
#define PG_MYHP_X100 15
#define PC_GOLD_TREASURE 100 // Treasure when our side holds this much camp gold, else Hunter
// Draft only: prism::plan_for_map() reads the map's layout (M: groups, altars, walks; never its identity) and returns Prism's carry
// plan: the safe bag, her farm and expected bag by r250/r500, our-side cluster gems and a viability flag. Where the plan is viable,
// Prism is our first pick and the rest come from the draft with her in the lineup; a lineup with her and no tank loses PZD_TANK_PP.
// The plan goes to draft-memory bytes 748-758 (inside the plan's checksum).
#define PZD_SIDE_PCT 60 // her groups: walkable, contest (our walk / both walks) <= this %, as in the plan
#define PZD_WALK 10 // rounds a visit adds to a group's respawn (her farm rate)
#define PZD_DPS 150 // team damage per round on her groups (kill time = group hp / this)
#define PZD_FA_PCT 100 // her farm: this % of her groups' rate, from her first walk on
#define PZD_TANK_PP 3.0f // a lineup with a viable Prism and no tank (RY MA VA HR) loses this

#include <cstddef>
#include <cstdint>
#include <vector>
#include "common.h"

namespace nova::prism {

// The draft's Prism map plan (draft-memory bytes 736-759), decoded on every body; defaults without a plan.
struct Plan
{
	bool ok = false; // a valid block was read
	std::uint8_t flags = 1;    // bit0 carry allowed, bit1 clusters (Prospector), bit2 Treasure (else Hunter), bit3 safe altar found
	int cap = PC_CAP_DEFAULT;  // bag cap (gems): what the safe window can bank (x1.5 once she holds Tribute)
	int altar[2] = { -1, -1 }; // the safest altars (index into M.altars), best first
	int altar_t[2] = { 0, 0 }; // their enemy walk minus 4 (turns a channel there has after an enemy leaves its spawn)
	int groups[4] = { -1, -1, -1, -1 }; // her gem groups (index into M.groups), richest first
};
extern Plan PL;

constexpr std::size_t PLAN_AT = 736, PLAN_END = 760; // draft memory: group/altar data end by 736; bytes 760-767 hold another block; strat 768-831; zone 832-1023
// Draft-memory block (bytes 736-759; free in every layout: the group/altar data stop at 16 + 3 x 240 = 736, bytes 760-767 hold
// another block, the strategy block 768-831, the zone block 832-1023): 736 magic 0x50, 737 version 1, 738 flags: bit0 carry allowed,
// bit1 clusters on our side and the middle (Prospector), bit2 Treasure (camp gold there >= PC_GOLD_TREASURE; else Hunter), bit3 a
// safe altar was found. 739 bag cap / 4 (gems): 10 x clamp(safe turns of the best altar, PC_CAP_TMIN, PC_CAP_TMAX). 740-741 the two
// safest altars (index into M.altars; 255 = none): enemy walk longest, our walk shorter. 742-743 their safe turns: the enemy spawn's
// walk to the altar's approach tiles minus 4 (spell range), capped 254. 744-747 her gem groups (index into M.groups; 255 = none):
// our side and the middle (contest <= 0.6), walk access, PC_ROUTE_GEMS+ gems, richest first. 748-758 the draft's carry plan
// (draft_prism.cc plan_bytes). 759 checksum: sum of 736-758 & 255.
constexpr std::uint8_t MAGIC = 0x50, VERSION = 1;
constexpr std::size_t N = PLAN_END - PLAN_AT;
void write_plan(std::vector<std::uint8_t>& mem); // draft side (needs M.done())
void read_plan();                                // play side, from cambc::draft_memory (after decode_memory's distances)

int prism_slot();       // our Prism body's slot, -1 if none
bool me_prism();        // I am the Prism
bool carry_on();        // carry mode: a Prism on our team and the plan allows it
int bag_of_prism(); // her carried gems (my own when I am her; else the SDK), -1 unknown
vec2 guard_post(); // her position when I am her guard, else {-1, -1}
vec2 pos_of_prism();    // her position (x < 0: unknown / dead)
bool prism_alive();
bool has_family(int fam); // I hold an emblem of this item family (0-13; cached 10 rounds; my own items only)
void fam_reset(); // drop the has_family cache (after a purchase)
bool has_tribute();     // she holds a Tribute emblem (family 7)
int channel_tick_count(int gems); // her tribute channel length for this bag
int cap_of_prism(); // her bag cap: 1 << 20 (greed rule: none), on any body
bool is_plan_group(int gi);
#define PF_GEMS 7
#define PF_R 12
#define PF_RANK 400
#define PF_FOE 6 // cap_rank: her funnel rank only with no visible enemy within this of the group
bool pf_group(int gi); // a gem group she should capture (map data only)
bool pc_group(int gi); // is_plan_group, or pf_group
void track();           // per turn: the enemy's tributed history (race deadline)
int foe_eta(); // rounds until the enemy reaches 1000 (a visible finishing channel by its timer, else its recent rate); BIG if unknown
bool foe_finishes_before_bank(int t_bank); // they could reach 1000 before (or about when) a bank started now would complete
bool prism_can_win_race(int gems, int t_bank); // a bank of this bag (done in t_bank rounds) can still win the race
bool race_deny(); // RACE_DENY: the race-deadline bank was refused lately and she carries RD_BAG+ gems
int nearest_known_enemy(); // Chebyshev distance to the nearest enemy champion known now (visible, ward, combat memory)
#define TG_BAG 60
#define TG_R 4
bool tribute_start_allowed(int gems);
// WSG: winning-bag start guard. A channel cannot act and damage never stops it: only a stun, a lock or the kill does, so the test is
// combat::channel_safe (stun reach + kill burst over the ticks). A non-Prism winning start with a known foe within 6 is often fatal,
// and restarts could slip through tribute_restart_hold's 4-tile radius and its 20-round window. Bit 1: a non-Prism winning bag (>=
// TG_BAG) with a known foe within WSG_R starts only if channel_safe(0, ticks). Bit 4: the same on Prism's winning start. Bit 2:
// new_tribute_blocked holds, within WSG_WIN rounds of an enemy-ended channel (any spot), while a known foe is within WSG_R and the
// restart is not channel_safe (non-Prism carrier). Bit 8: the same for the Prism carrier. Race guard (all bits): start anyway when
// foe_finishes_before_bank(ticks) or the channel would end at round >= 1990.
#define WSG_BITS 15
#define WSG_R 6
#define WSG_WIN 100
inline constexpr int WSG_TAB[4] = { 0x57534731, WSG_BITS, WSG_R, WSG_WIN };
// WSI: the WSG bit 2/8 new_tribute_blocked window would block a restart for any known foe within WSG_R, up to 99 rounds after a channel ended
// elsewhere by some foe. Bit 1: when my last channel was ended by the enemy, I note the enemy champions within WSI_R of me then
// (seen this or the last WSI_RECENT rounds, ally view included); the window blocks only while one of them (alive) is visible within
// WSG_R or its last-seen position is (with no note taken: any foe counts). Bit 2 (with bit 1): a last-seen position counts only
// while at most WSI_AGE rounds old.
#define WSI_BITS 1
#define WSI_R 8
#define WSI_RECENT 2
#define WSI_AGE 10
inline constexpr int WSI_TAB[5] = { 0x57534931, WSI_BITS, WSI_R, WSI_RECENT, WSI_AGE };
// RACE: the foe-finish prediction behind foe_finishes_before_bank. The owner Prism bank rules are not affected; only the foe-finish
// prediction. RACE_TAB[1] bits: 1: foe_finishes_before_bank's rate test is foe_finish_eta() <= t_bank + PC_RACE_T (foe_finish_eta =
// min(LINEAR, BAGS), race_estimate.h). 2: drop the flat 'them >=
// 1000 - race gems' clause (mostly false alarms; it skipped every safety test); the flat-clause exception is gone with it.
// 4: prism_can_win_race's foe time ('left') = foe_finish_eta() instead of the linear rate. Constants: bank
// probability p = RFE_P100 / 100, rate weight q = RFE_Q100 / 100, rate lag RFE_L rounds, walk factor k = RFE_K10 / 10 per Chebyshev
// tile to the nearest altar, a last-seen bag counts RFE_AGE rounds.
#define RFE_BITS 7
#define RFE_P100 85
#define RFE_Q100 90
#define RFE_L 20
#define RFE_K10 30
#define RFE_AGE 60
inline constexpr int RACE_TAB[7] = { 0x52414331, RFE_BITS, RFE_P100, RFE_Q100, RFE_L, RFE_K10, RFE_AGE };
// RACE: rounds from now until the foe team's 1000th gem is credited (min of LINEAR and BAGS); 1e9 when neither predicts
double foe_finish_eta();
bool winning_tribute_start_blocked(int gems); // WSG: a known foe within WSG_R can stop this channel (not channel_safe) and no race forces the start
bool channel_start_ok(int gems); // no known enemy within PC_CHAN_R (always true below PC_CHAN_BAG)
bool pfb_team_wins(int gems); // v7xx PFB bit 2: tributed + this bag + my mates' carried bags reach WIN_TRIBUTE (prism_holds_bank's why 6)
bool channel_doomed(); // channel_doomed: in a tribute channel of PC_CHAN_BAG+ with 2+ turns left and a known enemy within PC_CHAN_R (but not while the bag wins the game and her HP >= PC_WIN_KEEP_HP percent)
bool channel_not_doomed(int gems, int walk, int chan); // channel_not_doomed: channel_doomed would not cancel a chan-tick channel of this bag opened walk rounds from now, with the nearest known foe walking straight in
bool spell_free(); // no enemy champion known within PC_SPELL_R
const distance_field* safe_altar_field(); // the field to the plan's safest altar (built once, fuel permitting)

} // namespace nova::prism

namespace nova::prism {

// Prism's carry plan from the map's layout (draft side). A pure function of M (needs M.done()): no static data, no cache. Fuel: one
// pass over the groups and their camps and one over the altars.
struct MapPlan
{
	bool ok = false;     // computed (M.done(), our spawn known)
	bool viable = false; // her carry pays: she is our first pick
	bool gold_free = false; // every camp is a gem cluster: gold only from kills
	int t_safe = 0; // safe channel turns at the safest altar: enemy walk - 4 (254 unreachable, 0 none)
	int t_safe2 = 0;     // ... at the second
	int n_alt = 0;       // walkable, ungated altars
	int cap = 0; // safe bag, cold: 10 x clamp(t_safe, PC_CAP_TMIN, PC_CAP_TMAX)
	int cap_trib = 0;    // with the Tribute emblem (channels a third shorter): cap x 3 / 2
	int cap_kill = 0;    // in a kill window (60-round respawn): 15 x (60 + t_safe), at most 1000
	int gems = 0; // gems of her groups (walkable, contest <= PZD_SIDE_PCT %), monolith groups apart
	int clu = 0;         // gem-cluster gems there (a bag of 27 one-shots 120-HP clusters with slot 1)
	int mono = 0;        // monolith-group gems there
	int gold = 0;        // camp gold there
	int n_groups = 0;    // her groups
	int d_first = 0; // our spawn's walk to the nearest of her groups with PC_ROUTE_GEMS+ gems (255 none)
	int rate = 0; // her groups' gems per 100 rounds: sum gems x 100 / (respawn + PZD_WALK + hp / PZD_DPS)
	int rate_max = 0;    // ... at respawn speed: sum gems x 100 / respawn
	int gems_all = 0;    // every walkable group's gems (both sides)
	int farm250 = 0, farm500 = 0; // gems she captures by r250 / r500 under carry
	int bag250 = 0, bag500 = 0;   // her expected bag at r250 / r500 (the farm, held up to the Tribute cap)
	long fuel = 0;       // fuel this call used
};
MapPlan plan_for_map();

} // namespace nova::prism

#include "world.h"

namespace nova::prism_layer {
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.kit->gem_focus; }                                     // I am Prism (+1.5 Focus a carried gem)
inline bool carrier() { return W.me.kit->gem_focus && prism::carry_on(); } // the kit has gem focus and carry mode is on
inline bool kit(const Kit& k) { return k.gem_focus; }                                // this kit is Prism (a mate, or *W.me.kit)
inline bool kit_carrier(const Kit& k) { return k.gem_focus && prism::carry_on(); }   // ... and carry mode runs
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::prism; } // this body is a Prism (ours or theirs)
inline bool type_carrier(cambc::champion_type t) { return t == cambc::champion_type::prism && prism::carry_on(); }
inline bool carrier_slot(int s) { return s == prism::prism_slot() && prism::carry_on(); } // slot s is our carrier

// ---------------------------------------------------------------- BANK (and her channel)
inline bool bank_own_rule() { return carrier(); } // econ want_bank: prism_holds_bank decides
inline bool bank_quiet_bar() { return me(); }          // econ want_bank: no foe for 40 rounds raises her bank bar to 70
inline bool bank_skip_dyn() { return me(); } // econ want_bank: the dynamic bank bar does not apply to her
inline bool bank_skip_dash() { return me(); } // econ bank_dist_via_hole_dash: the dash bank does not apply to her
inline bool bank_skip_fhb() { return carrier(); }      // econ finish_bank_bag_slow: no slow-bag bank
inline bool bank_skip_bus() { return me(); } // econ bank_first: the small-bag bank does not apply to her
inline bool bank_skip_ebk() { return carrier(); }      // econ bag_wins_with_mates: the team-sum win bank is not hers
inline bool bank_skip_wbf() { return carrier(); } // econ winning_bag_flipflop_blocks: WBF does not apply to her (channel_start_ok guards her)
inline bool bank_skip_ffw() { return me(); } // econ winning_bag_flipflop_clear: FFW bit 1 keeps her race deadline
inline bool bank_safe_altar() { return carrier(); } // econ recall_bank_saves_walk / bank: the plan's safest altar
inline bool chan_guard() { return carrier(); } // econ bank / winning_bag_flipflop_blocks: no long channel near a foe
inline bool chan_camp_move() { return carrier(); } // econ bank: PC_CHAN_BAG+ bags step off camp reach first
inline bool chan_safe() { return carrier(); } // econ bank: the unsafe-channel test (prism_channel_unsafe)
inline bool chan_skip_trib_ok() { return carrier(); }  // econ bank: tribute_start_allowed is not hers (channel_start_ok is)
inline bool chan_doom_cancel() { return carrier(); } // brain channel_holds: cancel a doomed long channel
inline bool chan_wsg_carrier() { return carrier(); } // brain new_tribute_blocked: WSG reads bit 8 for her, bit 2 for others
inline bool ss_bag_skip() { return me(); }             // econ spawn_siege_turn: the big-bag rally rule is not hers

// ---------------------------------------------------------------- RECALL
inline bool recall_keeps_bag() { return carrier(); }   // econ capture_recall: her bag is never a reason to recall
inline bool recall_skip_bsr() { return me(); } // econ capture_recall: the bank-on-shop rule does not apply to her
inline bool recall_rhg_skip() { return me(); } // econ recall_hop_cost: the recall-hop term does not apply to her
inline bool recall_hold6() { return me(); } // econ travel recall: a pc_hold_why of 6 blocks it for her
inline bool shop_recall_keeps_bag() { return carrier(); } // brain shop_recall_slow: no bank first, she keeps her bag

// ---------------------------------------------------------------- RETREAT
inline bool exit_rule() { return me(); } // move escape: the exit rule for escape_to_safe_tile, with a bag

// ---------------------------------------------------------------- TARGETS
inline bool route_skip_bh89() { return me(); } // econ bank_hop_from_here: no crystal launch for her
inline bool cr_rich() { return me(); } // econ hold and chip sites (chip_start_partial_clear, wait_chip_target): she counts as a rich (CR_BAG) bag
inline bool phm() { return me(); } // econ prism_mate_factor / prism_mate_bound: PHM, her own groups
inline bool squad_skip() { return me(); }              // econ dom_commit_contested / gate_target_turn: she joins no squad operation
inline bool squad_skip_slot(int s) { return prism::carry_on() && s == prism::prism_slot(); } // econ gate_target_turn: nor is counted in one
inline bool px_longer_rule() { return me(); } // econ prism_exit_walk_longer: the exit rule's longer path
inline bool cnw_own() { return me(); } // econ intel_cleared: a mate may hold this capture for her
inline bool shop_skip_grt() { return me(); } // econ greed_tail_pass: GRT does not apply to her (with healers and Tavi)

// ---------------------------------------------------------------- SHOP
inline bool shop_own_gold_rows() { return carrier(); } // econ emblem_gold_refresh: she keeps her own gold rows
inline bool shop_health_build(const Kit& k) { return kit_carrier(k); } // econ make_build: prism_carrier_shop_build, Health only
inline bool shop_health_stat(const Kit& k) { return kit(k); } // econ make_build: her stat is Health
inline bool shop_skip_emb(const Kit& k) { return kit_carrier(k); } // econ emblem window: not hers (as healers)
inline bool shop_wbt() { return me(); } // econ shop: WBT, a WBT_BAG+ bag
inline bool focus_from_bag(const Kit& k) { return kit(k); } // econ shards_of: her Focus is her bag, not Focus shards

// ---------------------------------------------------------------- FIGHT
inline bool fight_skip_ffw() { return me(); } // brain early_stages: the early-stage fight skip does not apply to her
inline bool fight_spell_free(const Kit& k) { return kit_carrier(k); } // combat camp_abilities: the spell hold on camps is lifted for her
// econ spawn_siege_my_dps / spawn_siege_kill_dps / crew soak: her slot 0 (1.5F + stun, GameRules.md:568-570) goes on camps despite
// the spell hold while no foe champion is known within PC_SPELL_R (camp_abilities' Prism term).
inline bool camp_stun_free_now() { return prism::spell_free(); }      // ... this turn, for a kit with fight_spell_free
inline bool fight_parting(const Kit& k) { return kit(k); } // combat parting_stun: hers only
inline bool fight_skip_cu() { return me(); } // combat cast_uptime_walk_in_free: the cast-uptime walk-in does not apply to her
} // namespace nova::prism_layer
// ---------------------------------------------------------------- DRAFT Her draft is its own file: draft_prism.cc (PRISM_DRAFT,
// PZD_RULE: pick() takes Prism first where her carry plan pays). The shared draft_*.cc terms that name her: N1_E_PR (n1), MCT bit
// PRISM, N1_PRMA.
// PBQ (b1807, Deep spec_pbq_1110.md, OWNER-APPROVED Prism bank changes 10 Nov). Runtime data flag PBQ_TAB, read first; 0 = v693; the Prism.
// Bit 8 (estimate): foe_finish_eta keeps a living foe's last-read bag >= PBQ_FB past RFE_AGE (up to PBQ_AGE rounds), a lower bound;
// FSB's banked test still drops it. Bits 1 (bag cap) and 2 (threat-bank channel_safe) were off at the v695 bake, which stripped their code; v698 drops their constants. PDA owns why 7.
#define PBQ_BITS 8
#define PBQ_FB 100
// v695 PBQ: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define PBQ_AGE 2000
inline constexpr int PBQ_TAB[4] = { 0x50425131, PBQ_BITS, PBQ_FB, PBQ_AGE }; // slot 0 magic keeps it out of .bss

// PSR (b2363; Prism Planner prism_inconsistency_audit_1113 item 1; behaviour). Runtime data flag PSR_TAB[1], read first; 0 = v891. Her camp
// spells (spell_free: camp_abilities' Prism term, camp_stun_free_now) are held with an enemy champion known within PC_SPELL_R (10), age
// PC_KNOWN_AGE (3); every other kit holds at 6 tiles / 2 rounds. Bit 1: radius PSR_TAB[2] (6), age PSR_TAB[3] (2). Bit 2: radius PSR_TAB[4] (4), age 2.
// v892 PSR: PSR camp spell hold radius 10 -> 6
#define PSR_BITS 1
inline constexpr int PSR_TAB[5] = { 0x50535231, PSR_BITS, 6, 2, 4 };
// b2379 PJM bits 256 / 512 COMBAT FORWARD (owner 13 Nov ~10:47Z, spec_pjm_1113.md last section): on the combat class (heavy_ge2 <= PJM_HG)
// 256: Prospector, Skirmish, Durability, then Treasure and the rest; 512: Skirmish, Prospector, Durability, ... Farm class: live order.
// b2379 PJM bit 64 TEMPO ORDER (owner 13 Nov ~04:13Z to the Prism Planner, spec_pjm_1113.md; VV 13 Nov: class heavy_ge2, built on live, not on
// bit 32). Runtime data flag PJM_TAB[1], read first; 0 = off. Our Prism carrier's emblems from slot 3: on maps with heavy_ge2 <= PJM_HG/1000
// (elk 15 + golem 36 gems per tile in groups without a monolith / all walkable group gems: little heavy camp value, a combat map) Durability
// then Skirmish; else (a farm map) Monster then Jungle; her later live order follows (a duplicate Durability is dropped). Draft-time map data.
#define PJM_BITS 256
// v893 PJM: PJM 256 Prism combat-class emblems (confirm)
#define PJM_HG 150
inline constexpr int PJM_TAB[3] = { 0x504A4D31, PJM_BITS, PJM_HG };
