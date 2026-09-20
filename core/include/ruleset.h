#pragma once

#include <cstdint>

#include "board.h"
#include "scoring.h"
#include "solver.h"

// Every generation parameter in one versioned struct. Nothing here has a
// meaningful default and nothing in a .cpp file may carry one of these
// numbers: the generation parameters are partly guesswork (spec 2.4) and
// every artifact derived from them records `configHash`, so a constant that
// lived in code would move a derived statistic without moving the hash.
//
// This is data only. Parsing and validation live in tools/config_json, which
// keeps core free of I/O for the iOS static library.

namespace fluxcore {

enum class Tier : uint8_t {
    Casual = 0,
    GoodCasual = 1,
    Spam = 2,
};
constexpr uint8_t kTierCount = 3;
constexpr uint8_t kMaxGrids = 2;
constexpr uint8_t kMaxSeedLengths = 8;

// How a board draws its best-of-N count from a CandidateRange.
//   UniformN        ruleset v1/v2: N uniform over [minN, maxN].
//   UniformQuality  ruleset v3: the client computes N = floor(quality^2)
//                   (flux-ios BoggleGenerator.generateBoard), so quality is the
//                   uniform variable, drawn over [sqrt(minN), sqrt(maxN)], and
//                   N is its square -- which is NOT uniform over [minN, maxN].
enum class CandidateDraw : uint8_t { UniformN = 0, UniformQuality = 1 };

// Whether each best-of-N candidate rolls its own seed (v1/v2), or the board
// draws one seed decision and one seed word before best-of-N and every
// candidate places that same word (v3, flux-ios SinglePlayerHomeView ->
// BoggleGenerator.generateBoard(seed:)).
enum class SeedScope : uint8_t { PerCandidate = 0, PerBoard = 1 };

// How a seed's path is laid.
//   BacktrackingDfs  v1/v2: randomized DFS with backtracking (LetterCounter port).
//   RandomWalk       v3: the client's walk -- random start, uniformly random
//                    unvisited neighbour each step, restart on a dead end.
enum class SeedPlacement : uint8_t { BacktrackingDfs = 0, RandomWalk = 1 };

// Order the non-seed cells are filled in. Only matters under a letter cap,
// where later draws see renormalized weights: the client fills in uniformly
// random order, so a fixed order would bias which cells get the leftovers.
enum class FillOrder : uint8_t { RowMajor = 0, Random = 1 };

// Best-of-N bounds, inclusive. How N is drawn inside them is
// RulesetConfig::candidateDraw; the realized value is recorded per board
// (spec 5.3).
struct CandidateRange {
    uint32_t minN = 0;
    uint32_t maxN = 0;
};

struct SeedLengthOption {
    uint8_t length = 0;
    uint32_t weight = 0;
    // The longest seed per grid (11 on 4x4, 13 on 5x5) appears only on Spam
    // boards (spec 2.3). Excluded options are dropped and the remaining
    // weights renormalized.
    bool spamOnly = false;
};

struct GridConfig {
    uint8_t side = 0;
    uint32_t share = 0;  // relative weight in the grid split (spec 2.3: 60/40)

    uint32_t tierShare[kTierCount] = {};
    CandidateRange candidates[kTierCount] = {};

    SeedLengthOption seedLengths[kMaxSeedLengths] = {};
    uint8_t seedLengthCount = 0;

    uint32_t tierShareTotal() const {
        uint32_t total = 0;
        for (uint8_t t = 0; t < kTierCount; ++t) total += tierShare[t];
        return total;
    }
};

struct RulesetConfig {
    uint32_t version = 0;

    // FNV-1a over the raw config file bytes. Stamped onto every derived
    // artifact; a mismatch means the numbers were produced under different
    // generation parameters and cannot be pooled.
    uint64_t configHash = 0;

    // Relative weights over A-Z. Provisional (spec 2.4): a placeholder for
    // whatever Flux actually uses, which may be Boggle-style dice.
    uint32_t letterWeights[26] = {};

    ScoreTable scores;

    GridConfig grids[kMaxGrids] = {};
    uint8_t gridCount = 0;

    // Integer probability so the draw is exactly reproducible across
    // compilers and platforms, which a double comparison would not be.
    uint32_t seedProbabilityPerMille = 0;

    // Additional seeds laid on top of the first one. Spec 2.3 describes a
    // single seed, so this is 0 unless someone is deliberately exploring the
    // dense overlapping clusters that `allowSeedOverlap` produces.
    uint32_t extraSeedCount = 0;

    // Lets a later seed reuse cells whose letters already agree, rather than
    // requiring untouched cells.
    bool allowSeedOverlap = false;

    uint32_t seedPathAttempts = 0;       // restarts of the self-avoiding walk
    uint32_t seedPlacementAttempts = 0;  // path draws before giving up on a word

    // Ruleset v3 generation semantics (spec 2.3, from flux-ios). The values
    // here are what v1/v2 configs load as, because those files predate the
    // `generation` block and must keep meaning what they meant; a v3 file has
    // to spell every one of them out.
    //
    // maxPerLetter: hard cap on copies of one letter per board, applied to
    // the seed (a seed word over the cap is never drawn) and to the fill (a
    // capped letter drops out and the other weights renormalize). 0 = none.
    uint8_t maxPerLetter = 0;
    FillOrder fillOrder = FillOrder::RowMajor;
    SeedScope seedScope = SeedScope::PerCandidate;
    SeedPlacement seedPlacement = SeedPlacement::BacktrackingDfs;
    CandidateDraw candidateDraw = CandidateDraw::UniformN;

    // The dictionary this ruleset was built for: Dawg::sourceHash() of the
    // DAWG every tool must load. Tools refuse to run against any other
    // dictionary when it is pinned (config_json's checkDictionary); v3 files
    // must pin it.
    bool dictionaryPinned = false;
    uint64_t dictionaryHash = 0;
    uint32_t dictionaryWords = 0;

    SolverOptions solver;

    // Cheap candidate scoring (spec 5.3). Off unless measured to pick the
    // same winner as full solving: a scorer that changes the winner
    // distribution biases every number built on best-of-N.
    bool cheapScoringEnabled = false;
    uint32_t cheapScoringMinStartCells = 0;  // cells scanned before any abort
    uint32_t cheapScoringMarginPerMille = 0;  // >1000 aborts less eagerly

    const GridConfig* grid(uint8_t side) const {
        for (uint8_t i = 0; i < gridCount; ++i) {
            if (grids[i].side == side) return &grids[i];
        }
        return nullptr;
    }

    uint32_t gridShareTotal() const {
        uint32_t total = 0;
        for (uint8_t i = 0; i < gridCount; ++i) total += grids[i].share;
        return total;
    }

    uint32_t letterWeightTotal() const {
        uint32_t total = 0;
        for (uint8_t i = 0; i < 26; ++i) total += letterWeights[i];
        return total;
    }
};

}  // namespace fluxcore
