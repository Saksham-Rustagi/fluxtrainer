#include "generator.h"

#include <algorithm>
#include <cmath>

namespace fluxcore {
namespace {

// Same edge walk the solver uses: scanning a state's edge run in order and
// summing the word counts of the siblings we skip gives the dense word ID of
// whatever we land on.
struct Step {
    uint32_t childState;
    uint32_t wordRank;
    uint32_t childRank;
    bool isWord;
    bool found;
};

inline Step stepEdge(const Dawg& dawg, uint32_t state, uint32_t rankBase, uint8_t letter) {
    Step step{};
    uint32_t edgeIdx = dawg.state(state).edgeStart;
    for (;;) {
        const DawgEdge& e = dawg.edge(edgeIdx);
        if (e.letter() == letter) {
            step.found = true;
            step.isWord = e.endOfWord();
            step.wordRank = rankBase;
            step.childRank = rankBase + (e.endOfWord() ? 1u : 0u);
            step.childState = e.childState();
            return step;
        }
        rankBase += (e.endOfWord() ? 1u : 0u) + dawg.state(e.childState()).wordCount;
        if (e.endOfList()) return step;
        ++edgeIdx;
    }
}

void enumerateWords(const Dawg& dawg, uint32_t state, uint32_t rankBase, uint8_t depth,
                    uint8_t minLen, uint8_t maxLen, std::vector<uint32_t>* byLength) {
    uint32_t edgeIdx = dawg.state(state).edgeStart;
    uint32_t rank = rankBase;
    for (;;) {
        const DawgEdge& e = dawg.edge(edgeIdx);
        const uint8_t len = static_cast<uint8_t>(depth + 1);
        uint32_t childRank = rank;
        if (e.endOfWord()) {
            if (len >= minLen && len <= maxLen) byLength[len].push_back(rank);
            ++childRank;
        }
        if (len < maxLen && dawg.hasEdges(e.childState())) {
            enumerateWords(dawg, e.childState(), childRank, len, minLen, maxLen, byLength);
        }
        rank = childRank + dawg.state(e.childState()).wordCount;
        if (e.endOfList()) return;
        ++edgeIdx;
    }
}

// Self-avoiding walk of exactly `targetLen` cells. The neighbour list is
// copied into a fixed-size array and shuffled in place -- the original in
// LetterCounter allocated a vector per DFS node, which is the hot path of
// seed placement.
bool dfsRandomPath(const BoardGeometry& geom, uint8_t targetLen, uint8_t cell, Rng& rng,
                   uint8_t* path, uint8_t* pathLen, uint32_t* visited) {
    path[(*pathLen)++] = cell;
    *visited |= 1u << cell;
    if (*pathLen == targetLen) return true;

    const uint8_t count = geom.neighborCount(cell);
    const uint8_t* src = geom.neighbors(cell);
    uint8_t neighbors[8];
    for (uint8_t i = 0; i < count; ++i) neighbors[i] = src[i];
    for (uint8_t i = count; i > 1; --i) {
        const uint32_t j = rng.below(i);
        std::swap(neighbors[i - 1], neighbors[j]);
    }

    for (uint8_t i = 0; i < count; ++i) {
        const uint8_t next = neighbors[i];
        if (*visited & (1u << next)) continue;
        if (dfsRandomPath(geom, targetLen, next, rng, path, pathLen, visited)) return true;
    }

    *visited &= ~(1u << cell);
    --(*pathLen);
    return false;
}

bool randomSelfAvoidingPath(const BoardGeometry& geom, uint8_t targetLen, uint32_t attempts,
                            Rng& rng, uint8_t* path) {
    const uint8_t cells = geom.cellCount();
    if (targetLen == 0 || targetLen > cells) return false;

    uint8_t starts[kMaxCells];
    for (uint8_t i = 0; i < cells; ++i) starts[i] = i;

    for (uint32_t attempt = 0; attempt < attempts; ++attempt) {
        for (uint8_t i = cells; i > 1; --i) {
            const uint32_t j = rng.below(i);
            std::swap(starts[i - 1], starts[j]);
        }
        for (uint8_t i = 0; i < cells; ++i) {
            uint8_t pathLen = 0;
            uint32_t visited = 0;
            if (dfsRandomPath(geom, targetLen, starts[i], rng, path, &pathLen, &visited)) {
                return true;
            }
        }
    }
    return false;
}

// The client's seed placement (flux-ios BoggleGenerator.generateRandomPath):
// a uniformly random start cell, then a uniformly random unvisited neighbour
// at each step, restarting from scratch on a dead end. No backtracking, which
// is why its path distribution differs from dfsRandomPath's.
bool randomWalkPath(const BoardGeometry& geom, uint8_t targetLen, uint32_t attempts, Rng& rng,
                    uint8_t* path) {
    const uint8_t cells = geom.cellCount();
    if (targetLen == 0 || targetLen > cells) return false;

    for (uint32_t attempt = 0; attempt < attempts; ++attempt) {
        uint8_t pathLen = 0;
        uint32_t visited = 0;
        uint8_t cell = static_cast<uint8_t>(rng.below(cells));
        path[pathLen++] = cell;
        visited |= 1u << cell;
        while (pathLen < targetLen) {
            uint8_t open[8];
            uint8_t openCount = 0;
            const uint8_t count = geom.neighborCount(cell);
            const uint8_t* neighbors = geom.neighbors(cell);
            for (uint8_t i = 0; i < count; ++i) {
                if (!(visited & (1u << neighbors[i]))) open[openCount++] = neighbors[i];
            }
            if (openCount == 0) break;
            cell = open[rng.below(openCount)];
            path[pathLen++] = cell;
            visited |= 1u << cell;
        }
        if (pathLen == targetLen) return true;
    }
    return false;
}

// (row, col) under the 8 dihedral symmetries of a square.
inline void transformCoord(uint8_t transform, uint8_t side, uint8_t r, uint8_t c, uint8_t* outR,
                           uint8_t* outC) {
    const uint8_t n = static_cast<uint8_t>(side - 1);
    switch (transform) {
        case 0: *outR = r; *outC = c; return;                                  // identity
        case 1: *outR = c; *outC = static_cast<uint8_t>(n - r); return;        // 90
        case 2: *outR = static_cast<uint8_t>(n - r); *outC = static_cast<uint8_t>(n - c); return;
        case 3: *outR = static_cast<uint8_t>(n - c); *outC = r; return;        // 270
        case 4: *outR = r; *outC = static_cast<uint8_t>(n - c); return;        // horizontal flip
        case 5: *outR = static_cast<uint8_t>(n - r); *outC = c; return;        // vertical flip
        case 6: *outR = c; *outC = r; return;                                  // main diagonal
        default: *outR = static_cast<uint8_t>(n - c); *outC = static_cast<uint8_t>(n - r); return;
    }
}

}  // namespace

uint32_t drawRealizedN(const CandidateRange& range, CandidateDraw draw, Rng& rng) {
    uint32_t n = range.minN;
    if (draw == CandidateDraw::UniformQuality) {
        const double low = std::sqrt(static_cast<double>(range.minN));
        const double high = std::sqrt(static_cast<double>(range.maxN));
        const double quality = low + (high - low) * rng.unit();
        const double squared = quality * quality;
        n = static_cast<uint32_t>(std::floor(squared));
        // sqrt then square can land a hair under minN; the range is inclusive.
        n = std::clamp(n, range.minN, range.maxN);
    } else {
        // Exactly v1's draw, including consuming nothing for a point range.
        const uint32_t span = range.maxN >= range.minN ? range.maxN - range.minN + 1 : 1;
        n = range.minN + rng.below(span);
    }
    return n == 0 ? 1 : n;
}

int realizedNQuartile(const CandidateRange& range, CandidateDraw draw, uint32_t realizedN) {
    if (range.maxN <= range.minN) return 0;
    double position = 0;
    if (draw == CandidateDraw::UniformQuality) {
        const double low = std::sqrt(static_cast<double>(range.minN));
        const double high = std::sqrt(static_cast<double>(range.maxN));
        // N = floor(q^2), so q lies in [sqrt(N), sqrt(N+1)); its midpoint
        // places N within the quality range without favouring either end.
        const double q = 0.5 * (std::sqrt(static_cast<double>(realizedN)) +
                                std::sqrt(static_cast<double>(realizedN) + 1.0));
        position = (q - low) / (high - low);
    } else {
        const double span = static_cast<double>(range.maxN - range.minN + 1);
        position = static_cast<double>(realizedN - range.minN) / span;
    }
    return std::clamp(static_cast<int>(position * 4.0), 0, 3);
}

bool fitsLetterCap(const char* word, uint8_t len, uint8_t maxPerLetter) {
    if (maxPerLetter == 0) return true;
    uint8_t counts[26] = {};
    for (uint8_t i = 0; i < len; ++i) {
        const int c = word[i] - 'A';
        if (c < 0 || c >= 26) return false;
        if (++counts[c] > maxPerLetter) return false;
    }
    return true;
}

void SeedPool::build(const Dawg& dawg, uint8_t minLen, uint8_t maxLen, uint8_t maxPerLetter) {
    for (uint8_t i = 0; i < kMaxLen; ++i) byLength_[i].clear();
    if (!dawg.isLoaded() || minLen == 0 || maxLen < minLen || maxLen >= kMaxLen) return;
    if (!dawg.hasEdges(dawg.rootState())) return;
    enumerateWords(dawg, dawg.rootState(), 0u, 0u, minLen, maxLen, byLength_);
    if (maxPerLetter == 0) return;

    // Spec 2.3: a seed word over the letter cap can never be drawn, since
    // laying it would put too many copies of a letter on the board (the
    // client's isValidSeedWord, maxRepeats 2).
    char letters[kMaxLen + 1];
    for (uint8_t len = minLen; len <= maxLen; ++len) {
        std::vector<uint32_t>& ids = byLength_[len];
        ids.erase(std::remove_if(ids.begin(), ids.end(),
                                 [&](uint32_t id) {
                                     const size_t n = dawg.wordForId(id, letters, sizeof(letters));
                                     return !fitsLetterCap(letters, static_cast<uint8_t>(n),
                                                           maxPerLetter);
                                 }),
                  ids.end());
    }
}

void SeedPool::buildForRuleset(const Dawg& dawg, const RulesetConfig& config) {
    uint8_t minLen = kMaxLen;
    uint8_t maxLen = 0;
    for (uint8_t g = 0; g < config.gridCount; ++g) {
        const GridConfig& grid = config.grids[g];
        for (uint8_t i = 0; i < grid.seedLengthCount; ++i) {
            const uint8_t len = grid.seedLengths[i].length;
            if (len == 0 || len >= kMaxLen) continue;
            minLen = std::min(minLen, len);
            maxLen = std::max(maxLen, len);
        }
    }
    if (maxLen == 0) {
        for (uint8_t i = 0; i < kMaxLen; ++i) byLength_[i].clear();
        return;
    }
    build(dawg, minLen, maxLen, config.maxPerLetter);
}

size_t SeedPool::totalWords() const {
    size_t total = 0;
    for (uint8_t i = 0; i < kMaxLen; ++i) total += byLength_[i].size();
    return total;
}

PotentialScorer::PotentialScorer(const Dawg& dawg, const RulesetConfig& config)
    : dawg_(dawg),
      scores_(config.scores),
      minWordLen_(config.solver.minWordLen),
      minStartCells_(config.cheapScoringMinStartCells),
      marginPerMille_(config.cheapScoringMarginPerMille) {
    stamp_.assign(dawg.wordCount(), 0u);
}

uint64_t PotentialScorer::score(const Board& board, const BoardGeometry& geom,
                                uint64_t leaderPoints, bool* aborted) {
    *aborted = false;
    points_ = 0;
    if (!dawg_.isLoaded() || board.side == 0 || board.side > kMaxSide) return 0;

    if (++generation_ == 0) {
        std::fill(stamp_.begin(), stamp_.end(), 0u);
        generation_ = 1;
    }

    board_ = &board;
    geom_ = &geom;

    const uint32_t root = dawg_.rootState();
    const uint8_t cells = geom.cellCount();
    for (uint8_t c = 0; c < cells; ++c) {
        const Step step = stepEdge(dawg_, root, 0u, board.letters[c]);
        if (step.found) {
            if (step.isWord && minWordLen_ <= 1 && stamp_[step.wordRank] != generation_) {
                stamp_[step.wordRank] = generation_;
                points_ += scores_.points(1);
            }
            if (cells > 1 && dawg_.hasEdges(step.childState)) {
                explore(c, step.childState, step.childRank, 1u << c, 1);
            }
        }

        // A word is scored at the start cell of its first path, so points
        // accumulate roughly linearly in start cells scanned. That makes the
        // scan-so-far a usable projection of the final total, and a candidate
        // whose projection is far enough under the leader cannot win.
        const uint32_t done = static_cast<uint32_t>(c) + 1;
        if (leaderPoints != 0 && done >= minStartCells_ && done < cells) {
            const uint64_t projected = points_ * cells / done;
            if (projected * marginPerMille_ < leaderPoints * 1000ull) {
                *aborted = true;
                return points_;
            }
        }
    }
    return points_;
}

void PotentialScorer::explore(uint8_t cell, uint32_t state, uint32_t rankBase, uint32_t visited,
                              uint8_t depth) {
    const uint8_t count = geom_->neighborCount(cell);
    const uint8_t* neighbors = geom_->neighbors(cell);
    const uint8_t nextDepth = static_cast<uint8_t>(depth + 1);

    for (uint8_t i = 0; i < count; ++i) {
        const uint8_t next = neighbors[i];
        const uint32_t bit = 1u << next;
        if (visited & bit) continue;

        const Step step = stepEdge(dawg_, state, rankBase, board_->letters[next]);
        if (!step.found) continue;

        if (step.isWord && nextDepth >= minWordLen_ && stamp_[step.wordRank] != generation_) {
            stamp_[step.wordRank] = generation_;
            points_ += scores_.points(nextDepth);
        }
        if (nextDepth < geom_->cellCount() && dawg_.hasEdges(step.childState)) {
            explore(next, step.childState, step.childRank, visited | bit, nextDepth);
        }
    }
}

Generator::Generator(const Dawg& dawg, const RulesetConfig& config, const SeedPool& seeds)
    : dawg_(dawg),
      config_(config),
      seeds_(seeds),
      solver_(dawg, config.scores, config.solver),
      scorer_(dawg, config),
      letterWeightTotal_(config.letterWeightTotal()) {}

bool Generator::generate(uint8_t side, Tier tier, uint32_t boardIndex, uint64_t rootSeed,
                         Board* outBoard, GenerationRecord* outRecord) {
    const GridConfig* grid = config_.grid(side);
    if (grid == nullptr || side == 0 || side > kMaxSide) return false;

    const uint64_t streamSeed = deriveBoardSeed(rootSeed, simulationCellId(side, tier), boardIndex);
    Rng boardRng(streamSeed);

    const CandidateRange& range = grid->candidates[static_cast<uint8_t>(tier)];
    const uint32_t realizedN = drawRealizedN(range, config_.candidateDraw, boardRng);

    // Spec 2.3 (v3): the seed decision and the seed word belong to the board,
    // drawn once before best-of-N; every candidate lays that same word on its
    // own path. Under PerCandidate (v1/v2) each candidate rolls its own.
    const bool perBoard = config_.seedScope == SeedScope::PerBoard;
    BoardSeed boardSeed;
    if (perBoard && boardRng.chance(config_.seedProbabilityPerMille, 1000)) {
        drawSeedWord(tier, *grid, boardRng, &boardSeed);
    }

    const BoardGeometry& geom = solver_.geometry(side);

    Candidate best;
    uint64_t bestPoints = 0;
    uint32_t bestIndex = 0;
    bool haveBest = false;
    uint32_t seededCandidates = 0;
    uint32_t placementFailures = 0;
    uint32_t cheapAborts = 0;

    for (uint32_t i = 0; i < realizedN; ++i) {
        // Each candidate gets its own stream, addressed by index. Candidate
        // construction therefore consumes exactly the same randomness however
        // the candidate is scored, so switching the cheap scorer on can only
        // change which candidate wins, never what the candidates are.
        Rng candidateRng(splitmix64(streamSeed ^ (0x632BE59BD9B4E019ull * (i + 1))));

        Candidate candidate;
        if (perBoard) {
            buildCandidateWithSeed(side, boardSeed, candidateRng, &candidate);
        } else {
            buildCandidate(side, tier, *grid, candidateRng, &candidate);
        }
        if (candidate.seeded) ++seededCandidates;
        if (candidate.placementFailed) ++placementFailures;
        // The client skips a candidate whose seed would not place (generateBoard
        // catches the throw and continues); it does not fall back to unseeded.
        if (perBoard && candidate.placementFailed) continue;

        uint64_t points = 0;
        bool aborted = false;
        if (config_.cheapScoringEnabled) {
            points = scorer_.score(candidate.board, geom, haveBest ? bestPoints : 0, &aborted);
            if (aborted) ++cheapAborts;
        } else {
            solver_.solve(candidate.board, SolveMode::Count, &scratch_);
            points = scratch_.totalPoints;
        }

        if (aborted) continue;
        if (!haveBest || points > bestPoints) {
            best = candidate;
            bestPoints = points;
            bestIndex = i;
            haveBest = true;
        }
    }

    if (!haveBest) {
        // Every candidate's seed failed to place -- possible only if the seed
        // length cannot be walked on this grid at all. Fall back to one
        // unseeded candidate rather than returning an empty board.
        Rng fallbackRng(splitmix64(streamSeed ^ 0xD6E8FEB86659FD93ull));
        best.board = Board{};
        best.board.side = side;
        fillRemaining(geom, 0u, fallbackRng, &best.board);
        solver_.solve(best.board, SolveMode::Count, &scratch_);
        bestPoints = scratch_.totalPoints;
    }

    *outBoard = best.board;

    GenerationRecord& record = *outRecord;
    record = GenerationRecord{};
    record.side = side;
    record.tier = tier;
    record.boardIndex = boardIndex;
    record.rootSeed = rootSeed;
    record.boardSeed = streamSeed;
    record.realizedN = realizedN;
    record.winningCandidate = bestIndex;
    record.winningPoints = bestPoints;
    record.seeded = best.seeded;
    record.seedWordId = best.seedWordId;
    record.seedLen = best.seedLen;
    record.seededCandidates = seededCandidates;
    record.seedPlacementFailures = placementFailures;
    record.cheapAborts = cheapAborts;
    record.rulesetVersion = config_.version;
    record.configHash = config_.configHash;
    return true;
}

void Generator::buildCandidate(uint8_t side, Tier tier, const GridConfig& grid, Rng& rng,
                               Candidate* out) const {
    Board& board = out->board;
    board = Board{};
    board.side = side;

    uint32_t filled = 0;
    if (rng.chance(config_.seedProbabilityPerMille, 1000)) {
        placeSeed(side, tier, grid, rng, &board, &filled, out);
    }
    fillRemaining(solver_.geometry(side), filled, rng, &board);
}

void Generator::buildCandidateWithSeed(uint8_t side, const BoardSeed& seed, Rng& rng,
                                       Candidate* out) const {
    Board& board = out->board;
    board = Board{};
    board.side = side;
    const BoardGeometry& geom = solver_.geometry(side);

    uint32_t filled = 0;
    if (seed.seeded) {
        if (!embedWord(seed.letters, seed.len, geom, rng, false, &board, &filled)) {
            out->placementFailed = true;
            return;
        }
        out->seeded = true;
        out->seedWordId = seed.wordId;
        out->seedLen = seed.len;
    }
    fillRemaining(geom, filled, rng, &board);
}

void Generator::fillRemaining(const BoardGeometry& geom, uint32_t filled, Rng& rng,
                              Board* board) const {
    const uint8_t cells = geom.cellCount();
    const uint8_t cap = config_.maxPerLetter;

    if (cap == 0 && config_.fillOrder == FillOrder::RowMajor) {
        for (uint8_t c = 0; c < cells; ++c) {
            if (filled & (1u << c)) continue;
            board->letters[c] = static_cast<uint8_t>(
                rng.pickWeighted(config_.letterWeights, 26, letterWeightTotal_));
        }
        return;
    }

    uint8_t order[kMaxCells];
    uint8_t remaining = 0;
    for (uint8_t c = 0; c < cells; ++c) {
        if (!(filled & (1u << c))) order[remaining++] = c;
    }
    if (config_.fillOrder == FillOrder::Random) {
        for (uint8_t i = remaining; i > 1; --i) {
            const uint32_t j = rng.below(i);
            std::swap(order[i - 1], order[j]);
        }
    }

    // Letters already on the board (the seed) count toward the cap.
    uint8_t counts[26] = {};
    for (uint8_t c = 0; c < cells; ++c) {
        if (filled & (1u << c)) ++counts[board->letters[c]];
    }
    uint32_t weights[26];
    uint32_t total = 0;
    for (uint8_t l = 0; l < 26; ++l) {
        weights[l] = (cap != 0 && counts[l] >= cap) ? 0u : config_.letterWeights[l];
        total += weights[l];
    }

    for (uint8_t k = 0; k < remaining; ++k) {
        // A capped letter's weight is zeroed, so the draw renormalizes over
        // the letters still available -- the client's positionOptions filter.
        const uint8_t letter = static_cast<uint8_t>(rng.pickWeighted(weights, 26, total));
        board->letters[order[k]] = letter;
        if (cap != 0 && ++counts[letter] >= cap) {
            total -= weights[letter];
            weights[letter] = 0;
        }
    }
}

bool Generator::drawSeedWord(Tier tier, const GridConfig& grid, Rng& rng, BoardSeed* out) const {
    uint32_t weights[kMaxSeedLengths] = {};
    uint32_t total = 0;
    for (uint8_t i = 0; i < grid.seedLengthCount; ++i) {
        const SeedLengthOption& option = grid.seedLengths[i];
        if (option.spamOnly && tier != Tier::Spam) continue;
        if (!seeds_.hasLength(option.length)) continue;
        weights[i] = option.weight;
        total += option.weight;
    }
    if (total == 0) return false;

    const uint32_t choice = rng.pickWeighted(weights, grid.seedLengthCount, total);
    const uint8_t length = grid.seedLengths[choice].length;
    const std::vector<uint32_t>& pool = seeds_.idsOfLength(length);
    if (pool.empty()) return false;

    const uint32_t wordId = pool[rng.below(static_cast<uint32_t>(pool.size()))];
    const size_t written = dawg_.wordForId(wordId, out->letters, sizeof(out->letters));
    if (written != length) return false;
    out->seeded = true;
    out->wordId = wordId;
    out->len = length;
    return true;
}

bool Generator::placeSeed(uint8_t side, Tier tier, const GridConfig& grid, Rng& rng, Board* board,
                          uint32_t* filled, Candidate* out) const {
    // The spam-only lengths drop out of the table for other tiers and the
    // remaining weights renormalize, which is what picking over the filtered
    // weight total does.
    uint32_t weights[kMaxSeedLengths] = {};
    uint32_t total = 0;
    for (uint8_t i = 0; i < grid.seedLengthCount; ++i) {
        const SeedLengthOption& option = grid.seedLengths[i];
        if (option.spamOnly && tier != Tier::Spam) continue;
        if (!seeds_.hasLength(option.length)) continue;
        weights[i] = option.weight;
        total += option.weight;
    }
    if (total == 0) return false;

    const uint32_t choice = rng.pickWeighted(weights, grid.seedLengthCount, total);
    const uint8_t length = grid.seedLengths[choice].length;
    const std::vector<uint32_t>& pool = seeds_.idsOfLength(length);
    if (pool.empty()) return false;

    const uint32_t wordId = pool[rng.below(static_cast<uint32_t>(pool.size()))];
    char letters[kMaxCells + 1];
    const size_t written = dawg_.wordForId(wordId, letters, sizeof(letters));
    if (written != length) return false;

    const BoardGeometry& geom = solver_.geometry(side);
    if (!embedWord(letters, length, geom, rng, false, board, filled)) {
        out->placementFailed = true;
        return false;
    }

    out->seeded = true;
    out->seedWordId = wordId;
    out->seedLen = length;

    for (uint32_t extra = 0; extra < config_.extraSeedCount; ++extra) {
        const std::vector<uint32_t>& extraPool = seeds_.idsOfLength(length);
        if (extraPool.empty()) break;
        const uint32_t extraId = extraPool[rng.below(static_cast<uint32_t>(extraPool.size()))];
        char extraLetters[kMaxCells + 1];
        const size_t extraWritten = dawg_.wordForId(extraId, extraLetters, sizeof(extraLetters));
        if (extraWritten != length) continue;
        embedWord(extraLetters, length, geom, rng, config_.allowSeedOverlap, board, filled);
    }
    return true;
}

bool Generator::embedWord(const char* word, uint8_t len, const BoardGeometry& geom, Rng& rng,
                          bool allowOverlap, Board* board, uint32_t* filled) const {
    if (len == 0 || len > geom.cellCount()) return false;

    uint8_t path[kMaxCells];
    for (uint32_t attempt = 0; attempt < config_.seedPlacementAttempts; ++attempt) {
        const bool placed =
            config_.seedPlacement == SeedPlacement::RandomWalk
                ? randomWalkPath(geom, len, config_.seedPathAttempts, rng, path)
                : randomSelfAvoidingPath(geom, len, config_.seedPathAttempts, rng, path);
        if (!placed) continue;

        bool ok = true;
        for (uint8_t i = 0; i < len; ++i) {
            const bool occupied = (*filled & (1u << path[i])) != 0;
            if (!occupied) continue;
            // In overlap mode a cell may be reused when the letter already
            // there agrees; this is what produces the dense overlapping
            // clusters real Spam boards have.
            if (!allowOverlap ||
                board->letters[path[i]] != static_cast<uint8_t>(word[i] - 'A')) {
                ok = false;
                break;
            }
        }
        if (!ok) continue;

        for (uint8_t i = 0; i < len; ++i) {
            board->letters[path[i]] = static_cast<uint8_t>(word[i] - 'A');
            *filled |= 1u << path[i];
        }
        return true;
    }
    return false;
}

uint8_t Generator::drawSide(Rng& rng) const {
    uint32_t weights[kMaxGrids] = {};
    for (uint8_t i = 0; i < config_.gridCount; ++i) weights[i] = config_.grids[i].share;
    const uint32_t choice = rng.pickWeighted(weights, config_.gridCount, config_.gridShareTotal());
    return config_.grids[choice].side;
}

Tier Generator::drawTier(uint8_t side, Rng& rng) const {
    const GridConfig* grid = config_.grid(side);
    if (grid == nullptr) return Tier::Casual;
    return static_cast<Tier>(
        rng.pickWeighted(grid->tierShare, kTierCount, grid->tierShareTotal()));
}

void canonicalizeBoard(const Board& board, Board* out) {
    *out = board;
    const uint8_t side = board.side;
    if (side == 0 || side > kMaxSide) return;

    Board image;
    image.side = side;
    for (uint8_t t = 1; t < 8; ++t) {
        for (uint8_t r = 0; r < side; ++r) {
            for (uint8_t c = 0; c < side; ++c) {
                uint8_t sr = 0, sc = 0;
                transformCoord(t, side, r, c, &sr, &sc);
                image.letters[r * side + c] = board.letters[sr * side + sc];
            }
        }
        const uint8_t cells = board.cellCount();
        if (std::lexicographical_compare(image.letters, image.letters + cells, out->letters,
                                         out->letters + cells)) {
            *out = image;
        }
    }
}

uint64_t canonicalBoardHash(const Board& board) {
    Board canonical;
    canonicalizeBoard(board, &canonical);

    uint64_t h = 1469598103934665603ull;  // FNV-1a 64-bit offset basis
    constexpr uint64_t prime = 1099511628211ull;
    h ^= canonical.side;
    h *= prime;
    for (uint8_t c = 0; c < canonical.cellCount(); ++c) {
        h ^= canonical.letters[c];
        h *= prime;
    }
    return h;
}

// Spec 11.1. Differs from generate() in two ways: every candidate has the
// target laid down before the fill, and a candidate only counts toward N if
// its potential lands inside the tier's norm band. Step 5 of 11.1 is what
// keeps these boards honest -- embedding a family raises density, so without
// the band check every training board drifts toward Spam.
bool Generator::generateConstrained(uint8_t side, Tier tier, const char* target, uint8_t targetLen,
                                    uint32_t boardIndex, uint64_t rootSeed, uint64_t normLow,
                                    uint64_t normHigh, uint32_t attemptBudget, Board* outBoard,
                                    GenerationRecord* outRecord, ConstrainedStats* outStats) {
    ConstrainedStats stats;
    const GridConfig* grid = config_.grid(side);
    if (grid == nullptr || side == 0 || side > kMaxSide || targetLen == 0) {
        if (outStats) *outStats = stats;
        return false;
    }

    // Under a letter cap a target over the cap can never be spelled, so no
    // amount of attempts produces a board; say so instead of burning the budget.
    if (!fitsLetterCap(target, targetLen, config_.maxPerLetter)) {
        stats.exhausted = true;
        if (outStats) *outStats = stats;
        return false;
    }

    const uint64_t boardSeed = deriveBoardSeed(rootSeed, simulationCellId(side, tier), boardIndex);
    Rng boardRng(boardSeed);

    const CandidateRange& range = grid->candidates[static_cast<uint8_t>(tier)];
    const uint32_t realizedN = drawRealizedN(range, config_.candidateDraw, boardRng);

    // Same seed semantics as generate(): under PerBoard the seed word is drawn
    // once for the board. It is dropped for a candidate where it would push a
    // letter past the cap alongside the target -- the target is the point of
    // a constrained board, the secret seed is not.
    const bool perBoard = config_.seedScope == SeedScope::PerBoard;
    BoardSeed sharedSeed;
    if (perBoard && boardRng.chance(config_.seedProbabilityPerMille, 1000)) {
        drawSeedWord(tier, *grid, boardRng, &sharedSeed);
    }

    const BoardGeometry& geom = solver_.geometry(side);

    Candidate best;
    uint64_t bestPoints = 0;
    bool haveBest = false;

    for (uint32_t attempt = 0; attempt < attemptBudget && stats.candidatesAccepted < realizedN;
         ++attempt) {
        Rng rng(splitmix64(boardSeed ^ (0x632BE59BD9B4E019ull * (attempt + 1))));

        Candidate candidate;
        candidate.board = Board{};
        candidate.board.side = side;
        uint32_t filled = 0;
        ++stats.candidatesBuilt;

        if (!embedWord(target, targetLen, geom, rng, false, &candidate.board, &filled)) {
            ++stats.placementFailures;
            continue;
        }
        // The target is laid first, but the board is otherwise generated
        // normally -- 11.1 step 6 runs the tier's ordinary best-of-N on top,
        // and a Spam board that dropped its seed would fall out of the tier's
        // own norm band by construction rather than by chance.
        if (perBoard) {
            if (sharedSeed.seeded) {
                char combined[2 * kMaxCells + 2];
                std::copy(target, target + targetLen, combined);
                std::copy(sharedSeed.letters, sharedSeed.letters + sharedSeed.len,
                          combined + targetLen);
                if (fitsLetterCap(combined, static_cast<uint8_t>(targetLen + sharedSeed.len),
                                  config_.maxPerLetter)) {
                    embedWord(sharedSeed.letters, sharedSeed.len, geom, rng, false,
                              &candidate.board, &filled);
                }
            }
        } else if (rng.chance(config_.seedProbabilityPerMille, 1000)) {
            placeSeed(side, tier, *grid, rng, &candidate.board, &filled, &candidate);
        }
        fillRemaining(geom, filled, rng, &candidate.board);

        solver_.solve(candidate.board, SolveMode::Count, &scratch_);
        ++stats.solves;
        const uint64_t points = scratch_.totalPoints;
        if (points < normLow || points > normHigh) {
            ++stats.normRejects;
            continue;
        }

        ++stats.candidatesAccepted;
        if (!haveBest || points > bestPoints) {
            best = candidate;
            bestPoints = points;
            haveBest = true;
        }
    }

    stats.exhausted = stats.candidatesAccepted < realizedN;
    if (outStats) *outStats = stats;
    if (!haveBest) return false;

    *outBoard = best.board;
    if (outRecord) {
        GenerationRecord& record = *outRecord;
        record = GenerationRecord{};
        record.side = side;
        record.tier = tier;
        record.boardIndex = boardIndex;
        record.rootSeed = rootSeed;
        record.boardSeed = boardSeed;
        record.realizedN = realizedN;
        record.winningPoints = bestPoints;
        record.seedPlacementFailures = stats.placementFailures;
        record.rulesetVersion = config_.version;
        record.configHash = config_.configHash;
    }
    return !stats.exhausted;
}

}  // namespace fluxcore
