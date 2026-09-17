#pragma once

#include <cstdint>

#include "board.h"

namespace fluxcore {

// Points by word length (spec 2.2). Deliberately carries no built-in table:
// the values are ruleset data loaded at runtime, not constants in code, so
// that changing them cannot silently change a derived statistic without the
// config hash moving too.
struct ScoreTable {
    uint32_t pointsByLength[kMaxCells + 1] = {};

    uint32_t points(uint8_t len) const { return len <= kMaxCells ? pointsByLength[len] : 0u; }
};

}  // namespace fluxcore
