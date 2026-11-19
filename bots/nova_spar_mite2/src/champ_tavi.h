#pragma once
// champ_tavi.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Tavi
// (GameRules.md:682-712). Ranged 3, HP 900 +75, Str 45 +5, Focus 110 +10. PASSIVE: buys shards anywhere (consumables only on spawn
// or dead); sells equipment on spawn at full purchase value (a whole emblem for 150, interactions.md:157). Health bought off spawn
// raises max HP without healing. Code: tavi_layer hooks, tavi_sell_emblems_buy_greed (champ_tavi.cc). Slot 0: reset. Slot 1: 1.6 x Focus and a
// one-round stun, range 4, excludes walking.
#include "common.h"
#include "world.h"

// TVG: rent-then-Greed for Tavi. Tavi sells an emblem on spawn for 150 (full value) and a shard for 30; 25 Greed shards combine into
// an emblem worth 40 shards of the stat (Health: +75 a shard, so +3,000 max HP). Bit 1: Tavi alive on own spawn at turn start, round
// >= [2], with gold + resale of his non-Greed items >= 750: sell items from the END of his build first (latest-planned emblems, then
// partial shards; items outside the build before both) until he holds 750, then buy 25 Greed shards of stat [3] (0 Strength, 1
// Focus, 2 Health); the shop then re-buys passives from what is left. Items in the first [4] build slots are never sold.
#define TVG_BITS 1
#define TVG_R0 0
#define TVG_STAT 0
#define TVG_KEEP 2
#define TVG_FUEL 40000 // skip the conversion on a turn with less fuel left (int literal, not a table)
namespace nova {
inline constexpr int TVG_TAB[5] = { 0x54564731, TVG_BITS, TVG_R0, TVG_STAT, TVG_KEEP }; // Tavi Greed rebuy, inert unless Tavi
} // namespace nova

namespace nova::tavi_layer {
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.type == cambc::champion_type::tavi; } // I am Tavi (TVG, champ_tavi.cc)
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::tavi; } // this body is a Tavi (ours or theirs)
// ---------------------------------------------------------------- SHOP
inline bool shop_anywhere() { return W.me.kit->remote_shop; }        // brain turn: he shops off spawn too
inline bool shop_skip_grt() { return W.me.type == cambc::champion_type::tavi; } // econ greed_tail_pass: GRT does not apply to him (with healers and Prism)
// ---------------------------------------------------------------- RECALL
inline bool recall_skip_shop() { return W.me.kit->remote_shop; }     // econ capture_recall / travel_recall_shop_due / shop recall: no trip home to shop
// ---------------------------------------------------------------- MODEL (multipliers.h fam memory)
inline bool fam_reread(cambc::champion_type t) { return t == cambc::champion_type::tavi; } // mu fam memory: his families change off spawn, re-read at age 3
} // namespace nova::tavi_layer

// ---------------------------------------------------------------- DRAFT (draft_*.cc set_values) Tavi is drafted down by DRAFT_TA_PP
// points.
#define DRAFT_TA_PP 4.0f
