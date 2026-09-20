#include "fluxclone_bridge.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>

#include "config_json.h"
#include "dawg.h"
#include "generator.h"
#include "ruleset.h"
#include "solver.h"

using namespace fluxcore;

struct FCEngine {
    Dawg dawg;
    RulesetConfig config;
    SeedPool seeds;
    std::unique_ptr<Generator> generator;
    std::unique_ptr<Solver> solver;
    SolveResult result;

    // Phase 3. A second solver, because the training path needs every word's
    // cells and the generator's solver is a Count-mode hot loop. The cap is 8
    // rather than the default 64: a drill lights one path and the review draws
    // one, and 8 is enough to pick the stem path that carries the most
    // branches without storing the hundreds a dense board has for a 3.
    std::unique_ptr<Solver> fullSolver;
    SolveResult full;
};

static void writeError(char* err, size_t errSize, const std::string& message) {
    if (err == nullptr || errSize == 0) return;
    std::snprintf(err, errSize, "%s", message.c_str());
}

FCEngine* fc_engine_create(const uint8_t* dawgData, size_t dawgSize, const char* configData,
                           size_t configSize, char* err, size_t errSize) {
    auto engine = std::make_unique<FCEngine>();
    if (!engine->dawg.loadFromMemory(dawgData, dawgSize)) {
        writeError(err, errSize, "DAWG failed to load");
        return nullptr;
    }
    config::LoadResult loaded;
    std::string error;
    if (!config::parseRulesetConfig(configData, configSize, "bundled ruleset", &loaded, &error)) {
        writeError(err, errSize, error);
        return nullptr;
    }
    if (!config::checkDictionary(loaded.config, engine->dawg.sourceHash(),
                                 engine->dawg.wordCount(), &error)) {
        writeError(err, errSize, error);
        return nullptr;
    }
    engine->config = loaded.config;
    engine->seeds.buildForRuleset(engine->dawg, engine->config);
    engine->generator = std::make_unique<Generator>(engine->dawg, engine->config, engine->seeds);
    engine->solver = std::make_unique<Solver>(engine->dawg, engine->config.scores,
                                              engine->config.solver);
    SolverOptions fullOptions = engine->config.solver;
    fullOptions.maxPathsPerWord = 8;
    engine->fullSolver = std::make_unique<Solver>(engine->dawg, engine->config.scores,
                                                  fullOptions);
    return engine.release();
}

void fc_engine_destroy(FCEngine* engine) { delete engine; }

uint32_t fc_engine_ruleset_version(const FCEngine* engine) { return engine->config.version; }
uint64_t fc_engine_config_hash(const FCEngine* engine) { return engine->config.configHash; }
uint64_t fc_engine_dictionary_hash(const FCEngine* engine) { return engine->dawg.sourceHash(); }
uint32_t fc_engine_dictionary_words(const FCEngine* engine) { return engine->dawg.wordCount(); }

uint8_t fc_engine_draw_tier(FCEngine* engine, uint8_t side, uint64_t rngSeed) {
    Rng rng(rngSeed);
    return static_cast<uint8_t>(engine->generator->drawTier(side, rng));
}

int fc_engine_generate(FCEngine* engine, uint8_t side, uint8_t tier, uint64_t rootSeed,
                       FCBoard* out) {
    if (engine == nullptr || out == nullptr || tier >= kTierCount) return 0;
    std::memset(out, 0, sizeof(*out));

    using Clock = std::chrono::steady_clock;
    const auto t0 = Clock::now();
    Board board;
    GenerationRecord record;
    if (!engine->generator->generate(side, static_cast<Tier>(tier), 0, rootSeed, &board,
                                     &record)) {
        return 0;
    }
    const auto t1 = Clock::now();
    engine->solver->solve(board, SolveMode::Count, &engine->result);
    const auto t2 = Clock::now();

    out->side = side;
    out->tier = tier;
    for (uint8_t i = 0; i < board.cellCount(); ++i) {
        out->letters[i] = static_cast<char>('A' + board.letters[i]);
    }
    out->rootSeed = rootSeed;
    out->boardSeed = record.boardSeed;
    out->realizedN = record.realizedN;
    out->seeded = record.seeded ? 1 : 0;
    if (record.seeded) {
        engine->dawg.wordForId(record.seedWordId, out->seedWord, sizeof(out->seedWord) - 1);
    }
    out->potentialPoints = engine->result.totalPoints;
    out->potentialWords = static_cast<uint32_t>(engine->result.wordCount());
    out->potentialWords5p = engine->result.wordsAtLeast5;
    out->generateMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    out->solveMs = std::chrono::duration<double, std::milli>(t2 - t1).count();
    return 1;
}

int fc_engine_word_id(const FCEngine* engine, const char* word, size_t len, uint32_t* outId) {
    return engine->dawg.findWordId(word, len, outId) ? 1 : 0;
}

// ---------------------------------------------------------------------------
// Phase 3
// ---------------------------------------------------------------------------

int fc_engine_generate_hook(FCEngine* engine, uint8_t side, uint8_t tier, const char* target,
                            size_t targetLen, uint64_t rootSeed, uint64_t normLow,
                            uint64_t normHigh, uint32_t minWords, uint32_t maxWords,
                            uint32_t attemptBudget, FCBoard* outBoard,
                            FCConstrainedStats* outStats) {
    if (engine == nullptr || outBoard == nullptr || tier >= kTierCount || targetLen == 0 ||
        targetLen > kMaxCells) {
        return 0;
    }
    std::memset(outBoard, 0, sizeof(*outBoard));
    Generator::ConstrainedStats stats;

    using Clock = std::chrono::steady_clock;
    const auto t0 = Clock::now();
    Board board;
    GenerationRecord record;
    const bool ok = engine->generator->generateConstrained(
        side, static_cast<Tier>(tier), target, static_cast<uint8_t>(targetLen), 0, rootSeed,
        normLow, normHigh, attemptBudget, &board, &record, &stats, minWords, maxWords);
    const auto t1 = Clock::now();

    if (outStats != nullptr) {
        outStats->candidatesBuilt = stats.candidatesBuilt;
        outStats->candidatesAccepted = stats.candidatesAccepted;
        outStats->solves = stats.solves;
        outStats->placementFailures = stats.placementFailures;
        outStats->normRejects = stats.normRejects;
        outStats->wordRejects = stats.wordRejects;
        outStats->exhausted = stats.exhausted ? 1 : 0;
        outStats->generateMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    }
    // generateConstrained returns false when the budget ran out before the
    // tier's full best-of-N, which is not the same as having no board: spec
    // 11.1's fallback ladder wants the board it did find, labelled honestly.
    if (!ok && stats.candidatesAccepted == 0) return 0;

    engine->solver->solve(board, SolveMode::Count, &engine->result);
    const auto t2 = Clock::now();

    outBoard->side = side;
    outBoard->tier = tier;
    for (uint8_t i = 0; i < board.cellCount(); ++i) {
        outBoard->letters[i] = static_cast<char>('A' + board.letters[i]);
    }
    outBoard->rootSeed = rootSeed;
    outBoard->boardSeed = record.boardSeed;
    outBoard->realizedN = record.realizedN;
    outBoard->seeded = record.seeded ? 1 : 0;
    if (record.seeded) {
        engine->dawg.wordForId(record.seedWordId, outBoard->seedWord,
                               sizeof(outBoard->seedWord) - 1);
    }
    outBoard->potentialPoints = engine->result.totalPoints;
    outBoard->potentialWords = static_cast<uint32_t>(engine->result.wordCount());
    outBoard->potentialWords5p = engine->result.wordsAtLeast5;
    outBoard->generateMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    outBoard->solveMs = std::chrono::duration<double, std::milli>(t2 - t1).count();
    return 1;
}

uint32_t fc_engine_solve(FCEngine* engine, uint8_t side, const char* letters,
                         FCSolveSummary* outSummary) {
    if (outSummary != nullptr) std::memset(outSummary, 0, sizeof(*outSummary));
    if (engine == nullptr || letters == nullptr || side == 0 || side > kMaxSide) return 0;

    Board board;
    board.side = side;
    const uint8_t cells = board.cellCount();
    for (uint8_t i = 0; i < cells; ++i) {
        const char c = letters[i];
        if (c < 'A' || c > 'Z') return 0;
        board.letters[i] = static_cast<uint8_t>(c - 'A');
    }

    using Clock = std::chrono::steady_clock;
    const auto t0 = Clock::now();
    engine->fullSolver->solve(board, SolveMode::Full, &engine->full);
    const auto t1 = Clock::now();

    if (outSummary != nullptr) {
        outSummary->words = static_cast<uint32_t>(engine->full.wordCount());
        outSummary->totalPoints = engine->full.totalPoints;
        outSummary->words5p = engine->full.wordsAtLeast5;
        outSummary->pathCapHit = engine->full.pathCapHit ? 1 : 0;
        outSummary->solveMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    }
    return static_cast<uint32_t>(engine->full.wordCount());
}

uint32_t fc_engine_solved_word(const FCEngine* engine, uint32_t i, char* out, size_t cap) {
    if (engine == nullptr || out == nullptr || cap == 0 || i >= engine->full.wordCount()) {
        if (out != nullptr && cap > 0) out[0] = '\0';
        return 0;
    }
    const size_t written = engine->dawg.wordForId(engine->full.wordIds[i], out, cap - 1);
    out[written] = '\0';
    return static_cast<uint32_t>(written);
}

uint32_t fc_engine_solved_path_count(const FCEngine* engine, uint32_t i) {
    if (engine == nullptr || i >= engine->full.wordCount()) return 0;
    return engine->full.pathCounts[i];
}

uint32_t fc_engine_solved_paths_stored(const FCEngine* engine, uint32_t i) {
    if (engine == nullptr || i >= engine->full.storedPathCounts.size()) return 0;
    return engine->full.storedPathCounts[i];
}

uint32_t fc_engine_solved_path(const FCEngine* engine, uint32_t i, uint32_t j, uint8_t* out,
                               size_t cap) {
    if (engine == nullptr || out == nullptr || i >= engine->full.wordCount()) return 0;
    if (j >= engine->full.storedPathCounts[i]) return 0;
    const uint8_t len = engine->full.wordLens[i];
    if (cap < len) return 0;
    const uint32_t start = engine->full.pathOffsets[i] + j * len;
    std::copy(engine->full.pathCells.begin() + start,
              engine->full.pathCells.begin() + start + len, out);
    return len;
}

int fc_engine_is_prefix(const FCEngine* engine, const char* prefix, size_t len) {
    const Dawg& dawg = engine->dawg;
    uint32_t state = dawg.rootState();
    for (size_t i = 0; i < len; ++i) {
        const char c = prefix[i];
        if (c < 'A' || c > 'Z' || !dawg.hasEdges(state)) return 0;
        const uint32_t letter = static_cast<uint32_t>(c - 'A');
        uint32_t edgeIdx = dawg.state(state).edgeStart;
        bool matched = false;
        while (edgeIdx < dawg.edgeCount()) {
            const DawgEdge& e = dawg.edge(edgeIdx);
            if (e.letter() == letter) {
                state = e.childState();
                matched = true;
                break;
            }
            if (e.endOfList()) break;
            ++edgeIdx;
        }
        if (!matched) return 0;
    }
    return 1;
}
