#include <cambc.h>
#include "draft.h"
#include <algorithm>
#include <vector>
#include "random.h"

void play_draft() {
    const auto chosen = cambc::draft::current_draft(cambc::team::ally);
    std::vector<cambc::champion_draft> available;
    for (int i = 0; i < 11; ++i) {
        auto pick = static_cast<cambc::champion_draft>(i);
        if (std::find(chosen.begin(), chosen.end(), pick) == chosen.end()) available.push_back(pick);
    }
    cambc::draft::pick(available.at(random_number(available.size())));
}
