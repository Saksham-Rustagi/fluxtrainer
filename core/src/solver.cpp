#include "solver.h"

#include <algorithm>

namespace fluxcore {
namespace {

// Result of consuming one letter from a DAWG state while carrying the dense
// word ID down with us.
//
// The numbered DAWG makes the ID fall out of the walk that was happening
// anyway: scanning a state's edge run in order and summing the word counts of
// the siblings we skip gives the rank of whatever we land on. This is the
// whole reason D1 built a numbered DAWG, and it is why Count mode never
// touches a string.
struct Step {
    uint32_t childState;
    uint32_t wordRank;   // dense ID of the word ending at this edge (valid when isWord)
    uint32_t childRank;  // accumulator to carry deeper
    bool isWord;
    bool found;
};

// Precondition: `state` has at least one outgoing edge (see Dawg::hasEdges).
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
        if (e.endOfList()) return step;  // found == false
        ++edgeIdx;
    }
}

}  // namespace

void SolveResult::clear() {
    wordIds.clear();
    wordLens.clear();
    pathCounts.clear();
    storedPathCounts.clear();
    pathOffsets.clear();
    pathCells.clear();
    totalPoints = 0;
    wordsAtLeast5 = 0;
    pathCapHit = false;
}

Solver::Solver(const Dawg& dawg, const ScoreTable& scores, const SolverOptions& options)
    : dawg_(dawg), scores_(scores), options_(options) {
    for (uint8_t side = 1; side <= kMaxSide; ++side) geoms_[side].reset(side);
    stamp_.assign(dawg.wordCount(), 0u);
    slot_.assign(dawg.wordCount(), 0u);
}

void Solver::solve(const Board& board, SolveMode mode, SolveResult* out) {
    out->clear();
    if (!dawg_.isLoaded() || board.side == 0 || board.side > kMaxSide) return;

    if (++generation_ == 0) {  // wrapped: every stamp is stale, start over
        std::fill(stamp_.begin(), stamp_.end(), 0u);
        generation_ = 1;
    }

    board_ = &board;
    geom_ = &geoms_[board.side];
    out_ = out;
    mode_ = mode;
    if (mode == SolveMode::Full) {
        scratchSlots_.clear();
        scratchCells_.clear();
    }

    const uint32_t root = dawg_.rootState();
    const uint8_t cells = geom_->cellCount();
    for (uint8_t c = 0; c < cells; ++c) {
        const Step step = stepEdge(dawg_, root, 0u, board.letters[c]);
        if (!step.found) continue;
        path_[0] = c;
        if (step.isWord && options_.minWordLen <= 1) emitWord(step.wordRank, 1);
        if (cells > 1 && dawg_.hasEdges(step.childState)) {
            explore(c, step.childState, step.childRank, 1u << c, 1);
        }
    }

    if (mode == SolveMode::Full) compactPaths();
}

void Solver::explore(uint8_t cell, uint32_t state, uint32_t rankBase, uint32_t visited, uint8_t depth) {
    const uint8_t count = geom_->neighborCount(cell);
    const uint8_t* neighbors = geom_->neighbors(cell);
    const uint8_t nextDepth = static_cast<uint8_t>(depth + 1);

    for (uint8_t i = 0; i < count; ++i) {
        const uint8_t next = neighbors[i];
        const uint32_t bit = 1u << next;
        if (visited & bit) continue;  // no tile reuse within a word (spec 2.1)

        const Step step = stepEdge(dawg_, state, rankBase, board_->letters[next]);
        if (!step.found) continue;

        path_[depth] = next;
        if (step.isWord && nextDepth >= options_.minWordLen) emitWord(step.wordRank, nextDepth);
        if (nextDepth < geom_->cellCount() && dawg_.hasEdges(step.childState)) {
            explore(next, step.childState, step.childRank, visited | bit, nextDepth);
        }
    }
}

void Solver::emitWord(uint32_t wordId, uint8_t len) {
    uint32_t slot;
    if (stamp_[wordId] != generation_) {
        stamp_[wordId] = generation_;
        slot = static_cast<uint32_t>(out_->wordIds.size());
        slot_[wordId] = slot;
        out_->wordIds.push_back(wordId);
        out_->wordLens.push_back(len);
        out_->pathCounts.push_back(0);
        // Counted once per word, not once per path (spec 2.3). Moving this
        // into the per-path branch below would rank boards by points no
        // player can capture.
        out_->totalPoints += scores_.points(len);
        if (len >= 5) ++out_->wordsAtLeast5;
    } else {
        slot = slot_[wordId];
    }

    const uint32_t seen = ++out_->pathCounts[slot];
    if (mode_ == SolveMode::Full) {
        if (seen <= options_.maxPathsPerWord) {
            scratchSlots_.push_back(slot);
            scratchCells_.insert(scratchCells_.end(), path_, path_ + len);
        } else {
            out_->pathCapHit = true;
        }
    }
}

// Paths are discovered interleaved across words, so Full mode stages them
// flat and groups them here in one pass: prefix-sum the per-word stored
// counts into offsets, then scatter.
void Solver::compactPaths() {
    const size_t words = out_->wordIds.size();
    out_->storedPathCounts.resize(words);
    out_->pathOffsets.resize(words);

    uint32_t offset = 0;
    for (size_t i = 0; i < words; ++i) {
        out_->storedPathCounts[i] = std::min(out_->pathCounts[i], options_.maxPathsPerWord);
        out_->pathOffsets[i] = offset;
        offset += out_->storedPathCounts[i] * out_->wordLens[i];
    }

    out_->pathCells.assign(offset, 0);
    cursor_.assign(words, 0u);

    size_t read = 0;
    for (const uint32_t slot : scratchSlots_) {
        const uint8_t len = out_->wordLens[slot];
        uint32_t& written = cursor_[slot];
        const size_t dest = out_->pathOffsets[slot] + static_cast<size_t>(written) * len;
        std::copy(scratchCells_.begin() + static_cast<ptrdiff_t>(read),
                  scratchCells_.begin() + static_cast<ptrdiff_t>(read + len),
                  out_->pathCells.begin() + static_cast<ptrdiff_t>(dest));
        ++written;
        read += len;
    }
}

}  // namespace fluxcore
