// probe 22: engine imports nova doesn't use (b1167, 4 Nov): vision::champions() (champion_at), bitboard reachable_tiles
// (bc_Bitboard_ReachableMask), distance_field compute_to / get. Prints their results every 50 turns, compared with the CLI.
#include <cambc.h>
#include <cstdio>
#include <unistd.h>
#include "draft.h"
int main() {
    int turn = 0;
    while (true) {
        if (cambc::is_draft()) { play_draft(); cambc::end_turn(); continue; }
        ++turn;
        if (turn % 50 == 1) {
            long n = 0, hp = 0;
            for (auto& c : cambc::vision::champions()) { n++; hp += (long)c.health(); }
            auto& me = cambc::self();
            auto p = me.position();
            auto walls = cambc::map::walls() | cambc::map::holes();
            auto reach = walls.reachable_tiles(p, 6);
            cambc::bitboard roots; roots.clear(); roots.set(p, true);
            cambc::bitboard dest = cambc::map::altars();
            cambc::bitboard visited{};
            cambc::distance_field df;
            df.compute_to(walls, roots, dest, visited);
            auto alt = dest.positions();
            int d = alt.empty() ? -1 : (int)df.get(alt[0]);
            char out[160]; int m = snprintf(out, sizeof out, "T %d champs %ld hp %ld reach %d d %d\n", turn, n, hp, (int)reach.count(), d);
            write(1, out, m);
        }
        cambc::end_turn();
    }
}
