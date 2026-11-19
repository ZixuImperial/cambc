#pragma once
// econ_linear_score.h: the linear target score: flags and interface. Used by choose_target, retarget and rate.
#include "common.h"
// econ_linear_score: best_group RANKS targets by a linear per-body profit S = linear_group_value x pen - t x m (each body pays its
// own time) instead of rate_for's ratio. T.rate keeps the old ratio, so siege_start_gate and the thresholds keep their scale. Flag
// LNR_BITS, 0 = off. Bit 1 LIN: the ranking (no altar term), the extended rating loop and the switch margin S_new > S_cur + m x a
// set factor. Bit 2 STAGGER: the crew's gather overlaps the clear when the first arriver can tank the camp until the next arrives.
// Bit 4 DENY: denial value of a contested group (only read with bit 8). Bit 8 RISK: Pen_risk = P10(d, HP) x t_at/10 x (bag + respawn
// x m) replaces G3's multiplicative risk factor. Bit 16 ALTAR: the altar detour is charged when the bag after this group reaches the
// bank bar. Bit 32 PCAP: the ranking's pen = P_cap(fs - mn, geo, attackers) x the kept factors (G3, the back-of-map factor, kill
// window, crew bonus without STAGGER); the contest, seen, pack, crew-guard, pair-deep, ECL and FREE factors are out of the ranking
// (the deep-lone reject stays). Bit 256 NOKW: the ranking drops the x1.30 kill window. Stage B (no guard removed, every term on top
// of rf_pen x rf_value): Bit 8 RISK: S -= P10(d, HP) x t/10 x (bag + 60 m + 100 w_gold), d = foes - our bodies within 8 (pen keeps
// G3's factor). Bit 4 DENY (with 8): + DNW% x (P_we - P_they|skip) x v x scarcity, only on maps whose gems per body < LNR_SCQ (low
// third). Bit 32 PCAP: pen x V x (T[fs-mn][geo]/.95)^(LNR_PCK/100), on top of every guard. Bit 128 SEED: opening_pick ranks each
// body's first target by S (m = r*, lambda 100) and the first target is held (no periodic re-rank) until an event: target changed or
// gone, a foe within 8 of me or the target, a crew mate leaves. Bit 512 PAVAIL: pen x V x exp(-t_walk / tau_foe[band][type]), t_walk
// = max(walk, respawn wait). Bit 1024 CHAIN: + m x (33 - L(dN)), dN = Chebyshev anchor distance to the nearest other group not
// respawning. Bit 2048 CREWLEAVE: a crew mate on my target drops its claim, posts an RTV retreat or dies: re-choose now (the switch
// test keeps it if still best). Bit 64 EVENT: with a target, re-choose only on an event (target state, capture paid, HP band, foes
// near me/target appear or leave, bag crossing the bank bar, a group within 4 not seen this leg) or every LNR_EVP rounds, instead of
// every 5.
#define LNR_BITS 2049
#define LNR_RELAX 50   // [2] past the ratio stop, rate candidates whose bound >= this % of the best ratio (and > m)
#define LNR_XCAP 3     // [3] at most this many extra ratings a choice
#define LNR_SWR -1 // [4] switch margin in rounds of m (-1: matched to the 1.18x ratio rule)
#define LNR_GK 150     // [5] rolling m: tributed gems per body-round x this/100 (gold and the bank lag)
#define LNR_HPHI 70 // [6] RISK: HP share at or above this % is the high-HP column
#define LNR_DNW 50 // [7] DENY weight %
#define LNR_BAGBAR 30 // [8] ALTAR: bag (gems) that makes the next trip bank
#define LNR_RESP 60 // [9] RISK: respawn rounds charged at m
#define LNR_EVP 12 // [10] EVENT: full re-rank at least every this many rounds
#define LNR_LAMBDA 120 // [11] m = this % of r*, my best ratio (100: the identity control)
#define LNR_NOALT 1    // [12] A4: the altar term out of t (0: kept, the identity control)
#define LNR_HOLD 0     // [13] A2: m held for the walk (0: re-taken from every loop's r*, the plumbing control)
#define LNR_SCQ 56 // [14] DENY only when the map's group gems per body < this (low third)
#define LNR_PCK 50 // [15] PCAP exponent k x100
inline constexpr int LNR_TAB[16] = { 0x4C4E5231, LNR_BITS, LNR_RELAX, LNR_XCAP, LNR_SWR, LNR_GK, LNR_HPHI, LNR_DNW, LNR_BAGBAR, LNR_RESP, LNR_EVP, LNR_LAMBDA, LNR_NOALT, LNR_HOLD, LNR_SCQ, LNR_PCK };
constexpr int LNR_B_LIN = 1, LNR_B_STAG = 2, LNR_B_DENY = 4, LNR_B_RISK = 8, LNR_B_ALT = 16, LNR_B_PCAP = 32, LNR_B_EVT = 64, LNR_B_SEED = 128, LNR_B_NOKW = 256, LNR_B_PAV = 512, LNR_B_CHN = 1024, LNR_B_CRL = 2048;
// LSP (b1762, spec_lsp_1109): map-aware LNR constants. Bit 1: LNR_LAMBDA, the switch factor and SQ_KEEP each = c0 + s x (P0 + sum
// Pi zi + P9 y1 + P10 y2) / 1000, clamped (lambda 100-150 %, switch 1.0-1.4, keep .5-1.0); s = range / sqrt(12). z1-z8: the draft's
// standardized map features (dmem extra LSP_XID, 4 bits each); y1: the candidate group's band (own -1, mid 0, theirs +1), y2: a foe
// known within 8 of its anchor. P00-P10 lambda, P11-P21 switch, P22-P32 keep. 0 = off.
#define LSP_BITS 1
#define LSP_P00 -20
#define LSP_P01 0
#define LSP_P02 0
#define LSP_P03 0
#define LSP_P04 0
#define LSP_P05 0
#define LSP_P06 -119
#define LSP_P07 190
#define LSP_P08 0
#define LSP_P09 -165
#define LSP_P10 0
#define LSP_P11 269
#define LSP_P12 0
#define LSP_P13 0
#define LSP_P14 0
#define LSP_P15 160
#define LSP_P16 0
#define LSP_P17 -197
#define LSP_P18 0
#define LSP_P19 0
#define LSP_P20 0
#define LSP_P21 0
#define LSP_P22 297
#define LSP_P23 0
#define LSP_P24 0
#define LSP_P25 0
#define LSP_P26 0
#define LSP_P27 -122
#define LSP_P28 0
#define LSP_P29 0
#define LSP_P30 0
#define LSP_P31 0
// v644 LSP: baked at its shipped value
#define LSP_P32 0
inline constexpr int LSP_TAB[36] = { 0x4C535031, LSP_BITS, LSP_P00, LSP_P01, LSP_P02, LSP_P03, LSP_P04, LSP_P05, LSP_P06, LSP_P07, LSP_P08, LSP_P09, LSP_P10, LSP_P11, LSP_P12, LSP_P13, LSP_P14, LSP_P15, LSP_P16, LSP_P17, LSP_P18, LSP_P19, LSP_P20, LSP_P21, LSP_P22, LSP_P23, LSP_P24, LSP_P25, LSP_P26, LSP_P27, LSP_P28, LSP_P29, LSP_P30, LSP_P31, LSP_P32, 0x4C535032 }; // magic at both ends keeps it out of .bss
#define LSP_XID 11 // dmem extra: LSP's 8 map features, 4 bits each
// PCAP (bit 32) table: P_cap x100 by fs - mn (-2..+3) x side (own <.4, mid, their >.6)
inline constexpr short LNR_PCAP[18] = { 95, 90, 95, 95, 86, 91, 84, 67, 77, 79, 57, 68, 72, 41, 48, 66, 33, 27 };
namespace nova::econ::linear_score
{
// rate_for's publish: this rating's time parts (only with a bit set)
void note(int gi, float alt_t, float clear_t, float dmg, float wait, int trav, int crew, int others, int recruits);
// best_group (mine, opened, bit 1)
void begin();                                // a new rating loop
void cand(int gi, int crew, float r);        // a rated candidate (rf_value/rf_pen/rf_time and note() hold its parts)
int pick(int caller, int* gi, int* crew, float* r); // the S-best (callers 1 best_group, 4 best_within, 6 choose_target_when_starved); 1 if it differs
void rate_cur(int caller);                   // the current target's S/B just rated (rate_for) into caller slot
bool keep_ok(int ca, int cb, float k); // the ratio test r_a >= k r_b in S terms (used by the keep and form squad checks)
// refresh_target: the switch test with the current target's parts just rated
int switch_test(int best, float sw); // 1 switch, 0 keep, -1 not this loop's pick (the ratio rule)
float linear_group_value(int gi, int self);
float lsp_switch(int gi); // LSP: the switch factor for candidate gi (LSP bit 1 only)
float lsp_keep(int gi);   // LSP: SQ_KEEP for candidate gi (LSP bit 1 only)
bool parts(int gi, float* a0, float* b, float* lm); // LAH: the S parts cand() would keep for gi's rating just made (false: not from it)
bool crew_left(); // CREWLEAVE (bit 2048): a crew mate on my target left since the last call
bool due(int eval_round); // bit 64: an event since the last choice (or the period)
} // namespace nova::econ::linear_score
