#include "config_json.h"
#include "generator.h"
#include "solver.h"
#include "thread_pool.h"

#include <cstdio>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

// Dumps one row per generated board: the letters and the per-board scalars.
// simulate deliberately aggregates and never keeps boards; this exists for the
// analyses that need the boards themselves -- fitting the base letter
// distribution against an observed post-selection marginal, testing positional
// structure, and building per-tier potential densities for classifying real
// boards. Same Generator, same Solver, same per-board RNG streams as simulate.
//
// Output columns:
//   side tier index realizedN points words words5plus longest seeded seedLen letters

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::Generator;
using fluxcore::GenerationRecord;
using fluxcore::SeedPool;
using fluxcore::SolveMode;
using fluxcore::SolveResult;
using fluxcore::Solver;
using fluxcore::Tier;
using namespace fluxtools;

namespace {

const char* tierName(Tier tier) {
    switch (tier) {
        case Tier::Casual: return "casual";
        case Tier::GoodCasual: return "goodCasual";
        case Tier::Spam: return "spam";
    }
    return "?";
}

std::vector<uint8_t> readFile(const std::string& path, bool* ok) {
    std::ifstream in(path, std::ios::binary);
    if (!in) { *ok = false; return {}; }
    *ok = true;
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 6) {
        std::cerr << "usage: genboards <ruleset.json> <dawg> <out.tsv> <boards-per-cell> <seed> [threads]\n";
        return 1;
    }
    const uint64_t boardsPerCell = std::stoull(argv[4]);
    const uint64_t rootSeed = std::stoull(argv[5]);
    unsigned threads = (argc > 6) ? static_cast<unsigned>(std::stoul(argv[6]))
                                  : std::thread::hardware_concurrency();
    if (threads == 0) threads = 1;

    fluxcore::config::LoadResult loaded;
    std::string error;
    if (!fluxcore::config::loadRulesetConfig(argv[1], &loaded, &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }
    bool ok = false;
    const std::vector<uint8_t> dawgBytes = readFile(argv[2], &ok);
    Dawg dawg;
    if (!ok || !dawg.loadFromMemory(dawgBytes.data(), dawgBytes.size())) {
        std::cerr << "error: cannot load DAWG " << argv[2] << "\n";
        return 1;
    }
    if (!fluxcore::config::enforceDictionary(loaded.config, dawg.sourceHash(), dawg.wordCount(),
                                             "genboards")) {
        return 1;
    }
    SeedPool seeds;
    seeds.buildForRuleset(dawg, loaded.config);

    std::ofstream out(argv[3], std::ios::binary);
    if (!out) { std::cerr << "error: cannot write " << argv[3] << "\n"; return 1; }
    out << "side\ttier\tindex\trealizedN\tpoints\twords\twords5plus\tlongest\tseeded\tseedLen\tletters\n";

    for (uint8_t side : {4, 5}) {
        for (Tier tier : {Tier::Casual, Tier::GoodCasual, Tier::Spam}) {
            std::vector<std::unique_ptr<Generator>> generators;
            std::vector<std::unique_ptr<Solver>> solvers;
            std::vector<SolveResult> scratch(threads);
            for (unsigned t = 0; t < threads; ++t) {
                generators.push_back(std::make_unique<Generator>(dawg, loaded.config, seeds));
                solvers.push_back(std::make_unique<Solver>(dawg, loaded.config.scores, loaded.config.solver));
            }
            std::vector<std::string> rows(boardsPerCell);
            parallelFor(boardsPerCell, threads, [&](uint64_t index, unsigned t) {
                Board board;
                GenerationRecord record;
                if (!generators[t]->generate(side, tier, static_cast<uint32_t>(index), rootSeed, &board,
                                             &record)) {
                    return;
                }
                SolveResult& result = scratch[t];
                solvers[t]->solve(board, SolveMode::Count, &result);
                uint8_t longest = 0;
                for (uint8_t len : result.wordLens) longest = len > longest ? len : longest;

                std::string letters(board.cellCount(), '?');
                for (uint8_t i = 0; i < board.cellCount(); ++i) letters[i] = static_cast<char>('A' + board.letters[i]);
                char buf[160];
                std::snprintf(buf, sizeof(buf), "%dx%d\t%s\t%llu\t%u\t%llu\t%zu\t%u\t%u\t%d\t%u\t", side, side,
                              tierName(tier), static_cast<unsigned long long>(index), record.realizedN,
                              static_cast<unsigned long long>(result.totalPoints), result.wordCount(),
                              result.wordsAtLeast5, longest, record.seeded ? 1 : 0, record.seedLen);
                rows[index] = std::string(buf) + letters + "\n";
            });
            for (const std::string& r : rows) out << r;
            std::fprintf(stderr, "  %dx%d %s: %llu boards\n", side, side, tierName(tier),
                         static_cast<unsigned long long>(boardsPerCell));
        }
    }
    std::fprintf(stderr, "genboards: config %016llx, seed %llu\n",
                 static_cast<unsigned long long>(loaded.config.configHash),
                 static_cast<unsigned long long>(rootSeed));
    return 0;
}
