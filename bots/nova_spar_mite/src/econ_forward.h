#pragma once
// econ_forward.h: Forward declarations: economy functions used before their definition.
namespace nova::econ {
namespace {
bool group_awake_raw(int gi);
__attribute__((noinline)) bool group_awake_slow(int gi);
int living_members_visible_raw(int gi, int* invisible);
__attribute__((noinline)) void refresh_owned_slow();
inline bool recall_frees_channel(const Body& a);
static int mid_hop_best_landing(vec2 p, const FView& v, vec2* out);
bool hpg_buy_wanted();
const std::array<int, 3>& gates_step(int gi);
float group_value(const GroupI& g, int gi, int self);
bool siege_map();
bool stranded();
bool dpx_leave(const distance_field* tf); // v7xx DPX bit 1
float cap_term(int self);
bool chip_candidate_group(const GroupI& g);
bool chip_group_is_quiet(int gi);
float chip_clear_share(const GroupI& g, const GroupMem& m, const Crew& c);
bool crew_ally_near(int gi, int self, const std::array<int, 8>& cl);
float crew_bonus(const GroupI& g);
float crew_group_k(const GroupI& g);
float crew_keff();
float crew_wait_limit(const GroupI& g);
static float contest_walk_factor(float x, std::uint16_t trav, int self);
bool foes_accounted_for_and_far(const GroupI& g);
float faf_F(const GroupI& g);
float faf_of(float F, int crew);
bool hc_group(int gi);
int hoard_region_id(int gi);
bool region_mate_claims(int gi, int self, const Claims& cl);
bool idle_recruit_open(int gi);
int foes_down_count(int ahead);
float opening_pack_factor(int gi);
float opportunity_factor(const GroupI& g, const GroupMem& m);
static float prism_mate_factor(const GroupI& g, int gi);
template <int DM>
float rate_for(int gi, int self, std::uint16_t trav, const Claims& cl, int max_extra, int* crew_out);
bool respawn_wait_lifted(int gi, int self, float wait);
bool team_feasible(int gi);
float territory_factor(const GroupI& g, int gi, int self, const std::array<int, 8>& cl, const GroupMem& m, bool bound);
void drop_target(int fail_rounds);
bool bounds_resume_ready();
void group_static_fill(GBS& s, const GroupI& g, int gi, bool sga);
float join_gain(int gi, int b, std::uint16_t trav, const Claims& cl, int arrive, int* crew_out);
void opening_bounds_save(const std::pair<float, int>* out, int nout, int gi);
bool reachable_target(int gi);
void set_target(int gi, float rate, int crew);
int dom_commit_decide();
bool dc_is(int gi);
__attribute__((always_inline)) inline bool dom_commit_turn();
int gate_group_target();
int pick_focus_raw(int gi, vec2 near);
bool hole_shortcut_is_top(int gi);
int hole_shortcut_len(int gi, vec2 p);
bool hole_shortcut_turn(int gi, const distance_field& F);
bool ht_choice();
void bail_ban_lift_lapsed();
void crew_wait_ban_pass();
const distance_field* ring_gate_field(int gi);
static __attribute__((noinline)) bool finish_bank_bag_slow();
bool siege_ally_alive(int s);
NOVA_INLINE bool sg_any();
__attribute__((always_inline)) bool sg_big(const GroupI& g);
int siege_enemies_near_group(int gi, int age);
int sg_op_group();
int siege_slot_arrival_eta(int s, int gi);
bool siege_clear_started(int gi);
void siege_note_bail(int gi);
} // namespace
__attribute__((noinline)) void emblem_observe_slow();
namespace {
int next_emblem_cost();
void hidden_camp_threats(vec2 p, std::vector<mv::Threat>& th);
} // namespace
__attribute__((noinline)) void tavi_sell_emblems_buy_greed_slow();
__attribute__((noinline)) bool altar_hold_turn_slow();
namespace {
std::uint16_t bank_dist_here();
const distance_field& bank_field();
} // namespace
__attribute__((noinline)) void bank_step_turn_slow();
static bool enemy_altar_lock_direct(vec2 altar, cambc::detail::altar_lock_info& out);
__attribute__((noinline)) bool leave_respawn_tile_slow();
__attribute__((noinline)) bool lock_hit_slow(bool refresh);
__attribute__((noinline)) bool hit_claimed_camp_in_range_slow();
static __attribute__((noinline)) bool bag_too_late_to_bank_slow(int gems);
static bool channel_survives_known_foes(int walk, int chan);
__attribute__((noinline)) bool bank_winning_bag_slow();
__attribute__((noinline)) void dead_end_cache_fill_slow(long reserve);
static int recall_loop_guard();
static void recall_loop_guard_record(int g);
} // namespace nova::econ
