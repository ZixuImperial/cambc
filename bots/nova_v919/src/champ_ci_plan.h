#pragma once
// champ_ci_plan.h: CI2, the from-scratch Cassi & Issac path (policy: condor-work/reports/ci_policy_v1_1108.md). Flag CI2_BITS, read
// first at every hook; 0 = off (identical to live). Bit 1: the base path, decisions 1, 3, 4, 5, 6, 9, 11, with 2, 7, 8 and the
// constants as data values. On top of bit 1 (path v2): 2 YIELD = a group a non-pair mate claims or reaches no later than me counts
// (1 - Y) for a pair body after the opening; 4 CAPTURE = at under half of the claimants' damage the pair body leaves the capture to a
// non-pair mate standing on the region; 8 UNSEEN = a fight I would start counts my out-of-sight partner's last-known effective HP;
// 16 LEAVE = a fight the price of death refuses, with a foe in reach and no contact yet, is left (FLEE), not stood in. While it is on, a Cassi or Issac body runs the shared logic plus this file; none of the old C&I rules
// (P1-P11 of design_ci_revamp2_1108.md) run. All other kits are untouched.
#define CI2_BITS 389
#define CI2_MATE_X100 0  // decision 2: extra target weight x100 for a group a non-pair mate is near (0-150)
#define CI2_BANK 25      // decision 7: bank when the pair's bag reaches this (15-40)
#define CI2_CASSI_HP 0   // decision 8: Health shards Cassi buys first (0, 3, 5)
#define CI2_STAND 3      // decision 4: Cassi's stand distance on camps (2-4)
#define CI2_L_X100 15    // decision 6: the pair fights only at ratio >= 1 + L / 100 ...
#define CI2_LB 0        // ... when the pair's bag is at least this
#define CI2_Y_X100 60    // bit 2: the discount Y x100 (0, 30, 60, 100)
#define CI2_KITE_G 2     // bit 128: a melee foe this close, stun down: Cassi moves away (2, 3)
#define CI2_ENTRY_R 125  // bit 512: open a fight at local HP ratio >= this / 100, or with more bodies within 6
// v640 CI2: baked at its shipped value
#define CI2_ENTRY_D 8    // bit 512: partner further than this also needs a mate within 6 or more bodies
inline constexpr int CI2_TAB[12] = { 0x43493250, CI2_BITS, CI2_MATE_X100, CI2_BANK, CI2_CASSI_HP, CI2_STAND, CI2_L_X100, CI2_LB, CI2_Y_X100, CI2_KITE_G, CI2_ENTRY_R, CI2_ENTRY_D };
#define CI2_ON(b) ((CI2_TAB[1] & (b)) != 0)
// CDP (b1741, spec_cdp_1109, CI Analyser; owner small-team pair deaths): at team size <= 4 (draft picks, the pair counted once) the pair's
// price-of-death bar uses L = CDP_L instead of CI2_L_X100 (15); team size 5 plays as live. Runtime data flag CDP_TAB[1], read first; 0 = off.
#define CDP_BITS 1
// v676 CDP: small-team pair death price L50 (CDP)
#define CDP_L 50
inline constexpr int CDP_TAB[3] = { 0x43445031, CDP_BITS, CDP_L }; // slot 0 magic keeps it out of .bss
// CGM (b1748, spec_cgm_1109): C&I bodies' gold weight. Bit 2: x CGM_K/100 for a C&I slot (bit 1, the emblem-lift form, not built:
// step 0 showed emblem_gold_weight lowers w, x0.78, for every body).
#define CGM_BITS 2
// v649 CGM: C&I bodies weigh gold x0.8 (more gems)
#define CGM_K 80
inline constexpr int CGM_TAB[3] = { 0x43474D31, CGM_BITS, CGM_K };
// b2345 PYC (RC X737 PYC1): yield_capture's partner branch yields only to a partner that claims the group (GR:196, GR:207;
// the other hand-off sites test claims()). Runtime data flag PYC_TAB[1], read first; 0 = v836. Bit 1 PYC1.
// v839 PYC: 2 fixes mtp1,pyc1
#define PYC_BITS 1
inline constexpr int PYC_TAB[2] = { 0x50594331, PYC_BITS };
// Bisect switches (diagnostic): bit 32 keeps the old fight half, bit 64 the old farming half. Kit test first, as CI2_ME. Here the
// link (leash, adoption, combo stun and priority) is off whenever bit 1 is on, whichever half is kept.
#define CI2_FIGHT() static_cast<bool>(nova::ci_layer::type(W.me.type))
#define CI2_FARM() static_cast<bool>(nova::ci_layer::type(W.me.type))

// b2345 PPY (RC X737 PPY1): on a group with a gem or gold cluster, when exactly one of the pair holds Prospector, that body
// stands (GR:297, GR:314: 25% of the holder's own cluster share). Runtime data flag PPY_TAB[1], read first; 0 = v836. Bit 1 PPY1.
// v841 PPY: PPY pair body with Prospector stands
#define PPY_BITS 1
inline constexpr int PPY_TAB[2] = { 0x50505931, PPY_BITS };
namespace nova::combat { struct Foe; struct Assessment; }
namespace nova::ci2
{
// ---- Decision 4: Cassi's stand on camps
int stand_r();             // the stand distance this turn: CI2_STAND, or 4 with a foe seen within 8
bool stand_exact();        // true when she stands exactly at stand_r (foe near), not inside it
void stand_goals(bitboard& goals, vec2 fp); // the goal tiles for a focus camp at fp
// ---- Decision 5: spells on camps. Called from camp_abilities for a C&I body
void camp_spells(const Kit& k, int focus_ci);
// ---- Decision 6: the strength term (body b's health when linked) and the price of death
float link_friend_h(const Body& b, float h, const nova::combat::Assessment& a);
// Fix pass (Rule Checker, bot_errors.md 314-317): the pair counts once, with the lower health and both bodies' damage.
const Body* merged_partner(float join_r);  // my visible partner within join_r, merged into my own strength (else nullptr)
bool cia_nuke_held(); // CIA bit 1: CIB bit 1 holds Cassi's camp nuke on a recent sighting
int pair_bag();                             // my bag + my partner's, its last-seen bag when out of sight (aged)
void death_price_bar(float& engage, int bag);
int kite_reach();                    // CKF bit 2: kite_now's G
bool kite_now();                     // bit 128: Cassi, melee foe within G, stun on cooldown
// ---- Decision 3: who stands on a capture
bool yield_capture(int gi);     // true: my partner stands on the region and takes it, so I leave
int work_rank(int slot, int gi); // capture-rank term for a C&I slot: the pair takes what the pair cleared
// ---- Decision 7: bags
bool bank_pair(int gems);
// ---- Decision 9: Issac one step above Cassi, never above the team's tank
int issac_order(int want);
// ---- Decision 8: gold
void build_pass();
bool shop_hold(std::size_t item_id, int have); // true: the first Health shards are done for now, skip this entry
} // namespace nova::ci2
