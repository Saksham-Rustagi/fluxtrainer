#include "fluxclone_bridge.h"

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
