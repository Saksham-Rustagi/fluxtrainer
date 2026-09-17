#include "board.h"

namespace fluxcore {

void BoardGeometry::reset(uint8_t side) {
    side_ = side;
    cellCount_ = static_cast<uint8_t>(side * side);
    for (uint8_t c = 0; c < kMaxCells; ++c) neighborCount_[c] = 0;

    for (int r = 0; r < side; ++r) {
        for (int c = 0; c < side; ++c) {
            const uint8_t index = static_cast<uint8_t>(r * side + c);
            uint8_t count = 0;
            for (int dr = -1; dr <= 1; ++dr) {
                for (int dc = -1; dc <= 1; ++dc) {
                    if (dr == 0 && dc == 0) continue;
                    const int nr = r + dr;
                    const int nc = c + dc;
                    if (nr < 0 || nr >= side || nc < 0 || nc >= side) continue;
                    neighbors_[index][count++] = static_cast<uint8_t>(nr * side + nc);
                }
            }
            neighborCount_[index] = count;
        }
    }
}

bool BoardGeometry::adjacent(uint8_t a, uint8_t b) const {
    for (uint8_t i = 0; i < neighborCount_[a]; ++i) {
        if (neighbors_[a][i] == b) return true;
    }
    return false;
}

}  // namespace fluxcore
