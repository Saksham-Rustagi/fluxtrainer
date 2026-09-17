#pragma once

#include <cstdint>

namespace fluxcore {

constexpr uint8_t kMaxSide = 5;
constexpr uint8_t kMaxCells = kMaxSide * kMaxSide;

// Letters are 0-25 (A-Z). Q and U are ordinary separate tiles -- there is no
// special-casing for Q anywhere in the engine (spec 2.1).
struct Board {
    uint8_t side = 4;
    uint8_t letters[kMaxCells] = {};

    uint8_t cellCount() const { return static_cast<uint8_t>(side * side); }
};

// 8-way adjacency for one side length, precomputed once and reused. Board
// size is a runtime value rather than a template parameter or a macro, so a
// single binary handles 4x4 and 5x5 without recompiling.
class BoardGeometry {
public:
    BoardGeometry() = default;
    explicit BoardGeometry(uint8_t side) { reset(side); }

    void reset(uint8_t side);

    uint8_t side() const { return side_; }
    uint8_t cellCount() const { return cellCount_; }
    uint8_t neighborCount(uint8_t cell) const { return neighborCount_[cell]; }
    const uint8_t* neighbors(uint8_t cell) const { return neighbors_[cell]; }

    bool adjacent(uint8_t a, uint8_t b) const;

private:
    uint8_t side_ = 0;
    uint8_t cellCount_ = 0;
    uint8_t neighborCount_[kMaxCells] = {};
    uint8_t neighbors_[kMaxCells][8] = {};
};

}  // namespace fluxcore
