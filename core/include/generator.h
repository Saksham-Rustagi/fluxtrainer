#pragma once

#include <cstdint>
#include <vector>

#include "board.h"
#include "dawg.h"
#include "ruleset.h"
#include "solver.h"

namespace fluxcore {

// splitmix64, used only to derive stream seeds. Pure function of its input,
// so a board's stream is addressable rather than sequential.
inline uint64_t splitmix64(uint64_t x) {
    uint64_t z = x + 0x9E3779B97F4A7C15ull;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

// xoshiro256++. Small, fast, and reproducible across platforms because every
// operation is on fixed-width unsigned integers.
class Rng {
public:
    explicit Rng(uint64_t seed) {
        for (int i = 0; i < 4; ++i) {
            seed += 0x9E3779B97F4A7C15ull;
            state_[i] = splitmix64(seed);
        }
    }

    uint64_t next() {
        const uint64_t result = rotl(state_[0] + state_[3], 23) + state_[0];
        const uint64_t t = state_[1] << 17;
        state_[2] ^= state_[0];
        state_[3] ^= state_[1];
        state_[1] ^= state_[2];
        state_[0] ^= state_[3];
        state_[2] ^= t;
        state_[3] = rotl(state_[3], 45);
        return result;
    }

    // Unbiased (Lemire with rejection), so a bound that is not a power of
    // two does not quietly skew a uniform draw the spec calls uniform.
    uint32_t below(uint32_t bound) {
        if (bound <= 1) return 0;
        uint64_t product = static_cast<uint64_t>(draw32()) * bound;
        uint32_t low = static_cast<uint32_t>(product);
        if (low < bound) {
            const uint32_t threshold = static_cast<uint32_t>(-static_cast<int32_t>(bound)) % bound;
            while (low < threshold) {
                product = static_cast<uint64_t>(draw32()) * bound;
                low = static_cast<uint32_t>(product);
            }
        }
        return static_cast<uint32_t>(product >> 32);
    }

    // Uniform on [0, 1) with 53 bits. IEEE-exact arithmetic on fixed-width
    // integers, so it is as reproducible across platforms as below().
    double unit() { return static_cast<double>(next() >> 11) * 0x1.0p-53; }

    bool chance(uint32_t numerator, uint32_t denominator) {
        return denominator != 0 && below(denominator) < numerator;
    }

    // Index into `weights` proportional to weight. `total` is passed in
    // because callers keep it precomputed.
    uint32_t pickWeighted(const uint32_t* weights, uint32_t count, uint32_t total) {
        if (total == 0) return 0;
        uint32_t roll = below(total);
        for (uint32_t i = 0; i < count; ++i) {
            if (roll < weights[i]) return i;
            roll -= weights[i];
        }
        return count - 1;
    }

private:
    uint32_t draw32() { return static_cast<uint32_t>(next() >> 32); }
    static uint64_t rotl(uint64_t x, int k) { return (x << k) | (x >> (64 - k)); }

    uint64_t state_[4] = {};
};

// The per-board stream seed. Derived from the board index rather than the
// worker thread, so output is identical at any thread count -- per-thread
// streams would make the byte-identical-reproducibility requirement depend
// on how many cores the machine has.
inline uint64_t deriveBoardSeed(uint64_t rootSeed, uint32_t cellId, uint32_t boardIndex) {
    const uint64_t mixed =
        splitmix64((static_cast<uint64_t>(cellId) << 32) ^
                   (static_cast<uint64_t>(boardIndex) * 0x9E3779B97F4A7C15ull));
    return splitmix64(rootSeed ^ mixed);
}

// One simulation cell: (grid, tier). Part of the stream derivation, so two
// cells never share a board stream.
inline uint32_t simulationCellId(uint8_t side, Tier tier) {
    return static_cast<uint32_t>(side) * kTierCount + static_cast<uint32_t>(tier);
}

// The realized best-of-N for one board (spec 2.3). UniformN draws N over
// [minN, maxN]; UniformQuality draws quality q uniformly over
// [sqrt(minN), sqrt(maxN)] and returns floor(q^2) clamped to the range, the
// client's N = floor(quality^2). UniformQuality always consumes one draw;
// UniformN reproduces v1's draw exactly, including consuming none for a
// point range.
uint32_t drawRealizedN(const CandidateRange& range, CandidateDraw draw, Rng& rng);

// Which quarter of the draw's probability mass N fell in, 0-3. Under
// UniformQuality the quarters are equal in quality, not in N, so this is
// what "split at the quartiles of realized N" means for a non-uniform N.
int realizedNQuartile(const CandidateRange& range, CandidateDraw draw, uint32_t realizedN);

// Does `word` fit on a board capped at `maxPerLetter` copies of each letter?
// 0 means uncapped. A word over the cap can never be spelled, whatever the
// board, since a path never reuses a cell.
bool fitsLetterCap(const char* word, uint8_t len, uint8_t maxPerLetter);

// Spec 5.3: the fields that have to survive the aggregation, because two
// generation parameters are spreads rather than points and averaging over
// them destroys information the curriculum needs.
struct GenerationRecord {
    uint8_t side = 0;
    Tier tier = Tier::Casual;
    uint32_t boardIndex = 0;
    uint64_t rootSeed = 0;
    uint64_t boardSeed = 0;

    uint32_t realizedN = 0;         // the N this board actually ran best-of
    uint32_t winningCandidate = 0;  // its index within [0, realizedN)
    uint64_t winningPoints = 0;     // SolveResult::totalPoints of the winner

    bool seeded = false;      // the winning board carries a seed
    uint32_t seedWordId = 0;  // dense DAWG word ID, valid when `seeded`
    uint8_t seedLen = 0;

    // Diagnostics. Under SeedScope::PerCandidate, `seededCandidates` against
    // realizedN is the base seed rate, and `seeded` can exceed it because
    // selection runs after seeding. Under PerBoard the board is seeded or not
    // before best-of-N, so seededCandidates is 0 or every placed candidate.
    uint32_t seededCandidates = 0;
    uint32_t seedPlacementFailures = 0;
    uint32_t cheapAborts = 0;

    uint32_t rulesetVersion = 0;
    uint64_t configHash = 0;
};

// Seed words bucketed by length, enumerated once from the DAWG. Holds word
// IDs, not strings: the letters come back from Dawg::wordForId at placement
// time, which costs one short walk and keeps this table small.
class SeedPool {
public:
    // maxPerLetter > 0 drops words with more copies of a letter than the cap.
    void build(const Dawg& dawg, uint8_t minLen, uint8_t maxLen, uint8_t maxPerLetter = 0);
    void buildForRuleset(const Dawg& dawg, const RulesetConfig& config);

    bool hasLength(uint8_t len) const { return len < kMaxLen && !byLength_[len].empty(); }
    const std::vector<uint32_t>& idsOfLength(uint8_t len) const { return byLength_[len]; }
    size_t totalWords() const;

private:
    static constexpr uint8_t kMaxLen = 32;
    std::vector<uint32_t> byLength_[kMaxLen];
};

// Board potential with an early exit. Scores exactly what Solver's
// totalPoints scores (each word once, spec 2.3) when it runs to completion;
// the difference is that it can give up on a candidate that is far enough
// behind the current best-of-N leader to be irrelevant.
class PotentialScorer {
public:
    PotentialScorer(const Dawg& dawg, const RulesetConfig& config);

    // `leaderPoints` of 0 disables the early exit. Sets *aborted when the
    // candidate was cut short, in which case the return value is a partial
    // score and the candidate must be discarded rather than compared.
    uint64_t score(const Board& board, const BoardGeometry& geom, uint64_t leaderPoints,
                   bool* aborted);

private:
    void explore(uint8_t cell, uint32_t state, uint32_t rankBase, uint32_t visited, uint8_t depth);

    const Dawg& dawg_;
    ScoreTable scores_;
    uint8_t minWordLen_ = 3;
    uint32_t minStartCells_ = 0;
    uint32_t marginPerMille_ = 0;

    std::vector<uint32_t> stamp_;
    uint32_t generation_ = 0;

    const Board* board_ = nullptr;
    const BoardGeometry* geom_ = nullptr;
    uint64_t points_ = 0;
};

class Generator {
public:
    Generator(const Dawg& dawg, const RulesetConfig& config, const SeedPool& seeds);

    // Deterministic in (side, tier, boardIndex, rootSeed) alone. Returns
    // false only if the config carries no entry for `side`.
    bool generate(uint8_t side, Tier tier, uint32_t boardIndex, uint64_t rootSeed, Board* outBoard,
                  GenerationRecord* outRecord);

    // What a constrained generation actually cost. Spec 11.1 warns that up to
    // 625 candidates each passing a 60-90% rejection filter is potentially
    // thousands of generate-solve cycles, and that the "under 1 second" in
    // 14.4 is the unconstrained number. These are the fields that answer it.
    struct ConstrainedStats {
        uint32_t candidatesBuilt = 0;
        uint32_t candidatesAccepted = 0;
        uint32_t solves = 0;
        uint32_t placementFailures = 0;
        uint32_t normRejects = 0;
        bool exhausted = false;
    };

    // Spec 11.1: lay `target` on the grid first, then run the tier's best-of-N
    // over candidates that all carry it and all land inside the tier's norm
    // band [normLow, normHigh]. Returns false if `attemptBudget` ran out
    // before N candidates were accepted, which is the infeasibility case the
    // fallback ladder in 11.1 exists for.
    bool generateConstrained(uint8_t side, Tier tier, const char* target, uint8_t targetLen,
                             uint32_t boardIndex, uint64_t rootSeed, uint64_t normLow,
                             uint64_t normHigh, uint32_t attemptBudget, Board* outBoard,
                             GenerationRecord* outRecord, ConstrainedStats* outStats);

    // The 60/40 grid split and the tier shares, for callers that want the
    // ranked mix rather than a stratified cell.
    uint8_t drawSide(Rng& rng) const;
    Tier drawTier(uint8_t side, Rng& rng) const;

    const RulesetConfig& config() const { return config_; }

private:
    struct Candidate {
        Board board;
        bool seeded = false;
        uint32_t seedWordId = 0;
        uint8_t seedLen = 0;
        bool placementFailed = false;
    };

    // A board-level seed, drawn once before best-of-N (SeedScope::PerBoard).
    struct BoardSeed {
        bool seeded = false;
        uint32_t wordId = 0;
        uint8_t len = 0;
        char letters[kMaxCells + 1] = {};
    };

    void buildCandidate(uint8_t side, Tier tier, const GridConfig& grid, Rng& rng,
                        Candidate* out) const;
    // PerBoard: lay the board's shared seed word on a fresh path, then fill.
    void buildCandidateWithSeed(uint8_t side, const BoardSeed& seed, Rng& rng,
                                Candidate* out) const;
    bool drawSeedWord(Tier tier, const GridConfig& grid, Rng& rng, BoardSeed* out) const;
    bool placeSeed(uint8_t side, Tier tier, const GridConfig& grid, Rng& rng, Board* board,
                   uint32_t* filled, Candidate* out) const;
    bool embedWord(const char* word, uint8_t len, const BoardGeometry& geom, Rng& rng,
                   bool allowOverlap, Board* board, uint32_t* filled) const;
    // Every cell not in `filled`, from the letter weights, honouring the
    // ruleset's letter cap (counting what is already on the board) and fill
    // order. With no cap and row-major order this consumes the stream exactly
    // as v1 did, so v1 boards reproduce byte for byte.
    void fillRemaining(const BoardGeometry& geom, uint32_t filled, Rng& rng, Board* board) const;

    const Dawg& dawg_;
    RulesetConfig config_;
    const SeedPool& seeds_;

    Solver solver_;
    PotentialScorer scorer_;
    SolveResult scratch_;

    uint32_t letterWeightTotal_ = 0;
};

// Canonical form under the 8 dihedral symmetries: the lexicographically
// smallest image of the board. Two boards are the same board up to rotation
// and reflection exactly when their canonical forms match, which is what
// board dedup (spec 11.4) and collapsing equivalent simulated boards need.
void canonicalizeBoard(const Board& board, Board* out);
uint64_t canonicalBoardHash(const Board& board);

}  // namespace fluxcore
