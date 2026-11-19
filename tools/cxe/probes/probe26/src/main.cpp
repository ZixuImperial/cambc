// probe 26 (5 Nov, Econ GRT grill): the engine's own item data for Greed and Power (cost, combine count, stat points of shard and
// emblem) and the champion's growth, printed on champion turn 1 as 'T' lines (no purchase needed).
#include <cambc.h>
#include <cstdio>
#include <unistd.h>
#include "draft.h"
namespace bc = cambc;
static void item(const char* nm, bc::item_family f, bc::item_stat s, bool shard) {
    auto it = bc::get_item_enum(f, s, shard);
    auto in = it.info();
    char out[200];
    int m = snprintf(out, sizeof out, "T %s %s cost %u combine %u hp %d str %d foc %d purch %d mag %.3f\n", nm, shard ? "shard" : "emblem",
                     in.cost, in.combine_count, in.health_points, in.strength_points, in.focus_points, (int)in.purchasable, in.passive_magnitude);
    write(1, out, m);
}
int main() {
    int turn = 0;
    while (true) {
        if (bc::is_draft()) { play_draft(); bc::end_turn(); continue; }
        if (++turn == 1) {
            auto bs = bc::self().base_stats();
            char out[200];
            int m = snprintf(out, sizeof out, "T growth str %.3f hp %.3f base_str %.3f base_hp %.3f\n", bs.strength_growth, bs.health_growth, bs.base_strength, bs.base_health);
            write(1, out, m);
            for (bool sh : {true, false}) {
                item("greed_str", bc::item_family::greed, bc::item_stat::strength, sh);
                item("greed_hp", bc::item_family::greed, bc::item_stat::health, sh);
                item("power_str", bc::item_family::power, bc::item_stat::strength, sh);
                item("monster_str", bc::item_family::monster, bc::item_stat::strength, sh);
            }
        }
        bc::end_turn();
    }
}
