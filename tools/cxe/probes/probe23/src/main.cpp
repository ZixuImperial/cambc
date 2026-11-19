// probe 23: vision::camp_at (cxe import camp_at -> Game_API_GetCamp, 4 Nov for puppet.py's foe bots). Every 25 turns: camp_at on
// every camp tile of every group (visible ones answer, the rest throw), on an off-map tile, and the fuel each call cost; printed
// and compared with the CLI by ehtest.py --probe probe23.
#include <cambc.h>
#include <cstdio>
#include <unistd.h>
#include <vector>
#include "draft.h"
int main() {
    int turn = 0;
    while (true) {
        if (cambc::is_draft()) { play_draft(); cambc::end_turn(); continue; }
        ++turn;
        if (turn % 25 == 1) {
            long seen = 0, miss = 0, hp = 0, used = 0;
            std::vector<cambc::vec2> at;
            for (auto& c : cambc::vision::camps()) at.push_back(c.position());
            auto me = cambc::self().position();
            at.push_back(me);                                  // a champion's tile: no camp
            at.push_back(cambc::vec2{me.x + 9, me.y + 9});      // often out of vision
            for (auto p : at) {
                auto f0 = cambc::fuel_remaining();
                try {
                    auto v = cambc::vision::camp_at(p);
                    seen++;
                    hp += (long)v.health();
                } catch (...) {
                    miss++;
                }
                used += (long)(f0 - cambc::fuel_remaining());
            }
            long off = 0;
            try { cambc::vision::camp_at(cambc::vec2{-1, -1}); } catch (...) { off = 1; }
            char out[160]; int m = snprintf(out, sizeof out, "T %d camp_at seen %ld miss %ld hp %ld fuel %ld off %ld vis %d\n", turn, seen, miss, hp, used, off,
                                            (int)cambc::vision::camps().size());
            write(1, out, m);
        }
        cambc::end_turn();
    }
}
