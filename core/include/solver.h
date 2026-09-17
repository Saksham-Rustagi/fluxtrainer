#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "board.h"
#include "dawg.h"
#include "scoring.h"

namespace fluxcore {

enum class SolveMode {
    Count,  // word IDs and path counts only -- the simulator hot loop
    Full,   // every distinct path per word -- family and reachability analysis
};

// Struct-of-arrays, one entry per DISTINCT word found on the board.
// Deliberately not a map<string, vector<vector<int>>>: the simulator touches
// these arrays millions of times and must never allocate or hash a string.
struct SolveResult {
    std::vector<uint32_t> wordIds;
    std::vector<uint8_t> wordLens;

    // Every distinct path that spells the word, including any beyond the
    // store cap. This is the true count, and word_stats' E[paths per board]
    // depends on it staying true.
    std::vector<uint32_t> pathCounts;

    // Full mode only. The paths for word i are the storedPathCounts[i]
    // consecutive runs of wordLens[i] cells starting at pathCells[pathOffsets[i]].
    std::vector<uint32_t> storedPathCounts;
    std::vector<uint32_t> pathOffsets;
    std::vector<uint8_t> pathCells;

    // Board potential. Each word contributes exactly once however many paths
    // spell it (spec 2.3) -- duplicates do not score twice in play, so
    // per-path counting would rank boards by points no player can capture.
    uint64_t totalPoints = 0;
    uint32_t wordsAtLeast5 = 0;

    // Set when some word had more paths than the store cap allowed. The
    // truncation is recorded rather than silent.
    bool pathCapHit = false;

    size_t wordCount() const { return wordIds.size(); }
    void clear();  // keeps capacity
};

struct SolverOptions {
    uint32_t maxPathsPerWord = 64;
    uint8_t minWordLen = 3;  // Flux scores from 3 (spec 2.2); the dictionary holds 2s
};

// One Solver per worker thread. All scratch is allocated once in the
// constructor and reused across solves; solve() does not allocate in the
// steady state.
class Solver {
public:
    Solver(const Dawg& dawg, const ScoreTable& scores, const SolverOptions& options = {});

    void solve(const Board& board, SolveMode mode, SolveResult* out);

    const SolverOptions& options() const { return options_; }
    const BoardGeometry& geometry(uint8_t side) const { return geoms_[side]; }

private:
    void explore(uint8_t cell, uint32_t state, uint32_t rankBase, uint32_t visited, uint8_t depth);
    void emitWord(uint32_t wordId, uint8_t len);
    void compactPaths();

    const Dawg& dawg_;
    ScoreTable scores_;
    SolverOptions options_;

    BoardGeometry geoms_[kMaxSide + 1];

    // Generation-stamped dedup, indexed by word ID, so nothing is cleared
    // between boards.
    std::vector<uint32_t> stamp_;
    std::vector<uint32_t> slot_;
    uint32_t generation_ = 0;

    // Full-mode path staging: paths are discovered interleaved across words,
    // so they are appended flat here and grouped by word once per solve.
    std::vector<uint32_t> scratchSlots_;
    std::vector<uint8_t> scratchCells_;
    std::vector<uint32_t> cursor_;

    // Per-solve state, set at the top of solve().
    const Board* board_ = nullptr;
    const BoardGeometry* geom_ = nullptr;
    SolveResult* out_ = nullptr;
    SolveMode mode_ = SolveMode::Count;
    uint8_t path_[kMaxCells] = {};
};

}  // namespace fluxcore
