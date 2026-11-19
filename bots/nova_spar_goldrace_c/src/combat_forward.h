#pragma once
// combat_forward.h: Forward declarations: combat functions used before their definition.
namespace nova::combat {
namespace kit_rules
{
namespace {
} // namespace
float passive_mult(const Body& b);
bool slot_excl(int slot);
bool slot_ready(const Body& b, int s);
} // namespace kit_rules
namespace geom
{
float danger_at(const Assessment& a, vec2 t);
namespace {
bool init_dash_landing_bad(vec2 t);
} // namespace
} // namespace geom
namespace dmg
{
namespace {
static inline int dps_slot_cd(const Body& b, bool me, int s);
} // namespace
} // namespace dmg
namespace foe_model
{
namespace {
Foe foe_of_calc(const Body& e, int idx);
__attribute__((noinline)) float group_pack_factor_slow(int gi);
} // namespace
} // namespace foe_model
namespace burst
{
static float foe_two_turn_damage(const Body& e, int d, float t1);
int reach_burst_turns(const Body& e);
bool bh81_stun2(const Body& e);
bool stun_takes_next_turn(const Body& e);
int stunned_foe_reach(const Body& e, int reach);
float stunned_foe_burst(const Body& e, float one_turn_burst);
namespace {
static __attribute__((noinline)) bool spell_kills_foe_slow(const Body& e, int d);
} // namespace
float lethal_burst_hit(const Body& e, int d, int cdh, bool* cast);
namespace {
__attribute__((noinline)) void lethal_burst_zones_slow(const Assessment& a, std::vector<std::pair<vec2, int>>& out);
} // namespace
float my_burst_m(const Body& f, int d, bool oc);
} // namespace burst
namespace mates
{
bool ally_in_contact_within(const Assessment& a, int r);
namespace {
__attribute__((noinline)) int react_attacker_slow();
} // namespace
} // namespace mates
namespace cast
{
namespace {
__attribute__((noinline)) bool end_stun_slow();
__attribute__((noinline)) bool heart_dash_end_slow();
__attribute__((noinline)) bool heart_dash_try_slow(vec2 keep);
__attribute__((noinline)) bool linked_pair_cast_kill_slow(int site);
} // namespace
bool cast_via_sdk(int slot, std::uint32_t kind, std::uint32_t handle, vec2 p);
namespace {
__attribute__((noinline)) bool support_move_slow(const Assessment& a);
} // namespace
} // namespace cast
namespace fight_turn
{
namespace {
__attribute__((noinline)) bool escape_dash_turn_slow(const Assessment& a);
__attribute__((noinline)) bool retreat_to_spawn_to_heal_slow(const Assessment& a);
__attribute__((noinline)) bool self_shield_after_hit_turn_slow();
} // namespace
} // namespace fight_turn
namespace flee_turn
{
namespace {
__attribute__((noinline)) bool continue_retreat_slow(const Assessment& a);
} // namespace
static __attribute__((always_inline)) inline bool in_my_range(const Body& e);
namespace {
__attribute__((noinline)) bool react_guard_slow(const Assessment& a);
} // namespace
static __attribute__((always_inline)) inline float refuge_burst_cap();
static __attribute__((always_inline)) inline void refuge_hit_back();
template <class Cost> static __attribute__((always_inline)) inline vec2 refuge_tile(float cap, bool no_camp_out, Cost cost);
static float tile_danger(const Assessment& a, vec2 t);
static float sru_in(float foe);
template <class Keep> static __attribute__((always_inline)) inline const Body* weakest_foe_where(Keep keep);
} // namespace flee_turn
namespace deny
{
namespace {
int locks_carried(); // CB3 bit 8 KWS reads it in kill_window
int game_deny_mates_ahead(vec2 tp, vec2 alt, int dme, int L, bool stunnable); // v703 R3G bit 1 RGY1 (combat_cast.cc esl2_lock_way_near)
__attribute__((noinline)) bool deny_tribute_slow();
__attribute__((noinline)) bool game_deny_slow(const Assessment& a);
} // namespace
} // namespace deny
namespace camps
{
} // namespace camps
namespace {
float eff_hp(const Body& b);
} // namespace
namespace camps
{
namespace {
__attribute__((noinline)) bool prestep_blocked(vec2 dest);
__attribute__((noinline)) void prestep_hit_before_move_slow(vec2 dest);
} // namespace
static bool foe_in_basic_range();
static bool hold_area_stun_on_immune_foes(vec2 t, int r, float dmg);
static inline bool sleeping_attacker_counts(const CampI& cp, vec2 me_after);
static inline bool nw_ci_ok(int ci);
static inline bool group_has_attackers(int g, int skip_g);
static inline bool nw_wakes_at(float str);
void refresh_cooldowns();
static bool camp_alive_in_engine(int ci);
} // namespace camps
namespace calm
{
namespace {
__attribute__((noinline)) bool assist_cast_slow();
__attribute__((noinline)) bool hidden_fire_slow();
__attribute__((noinline)) bool kite_shot_after_move_slow();
__attribute__((noinline)) bool spell_poke_slow(const Assessment& a);
} // namespace
} // namespace calm
namespace pair
{
static int pick_spell_kill_foe(int site, const Body*& out, vec2& tile);
} // namespace pair
} // namespace nova::combat
