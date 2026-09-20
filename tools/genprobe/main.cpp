#include "config_json.h"
#include "generator.h"
#include "solver.h"
#include "stats.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

// Spec 11.1 / 15: constrained generation has to be benchmarked in Phase 1,
// not Phase 4. The warning in 11.1 is specific -- up to 625 candidates, each
// passing a 60-90% rejection filter, is potentially thousands of
// generate-solve cycles, and the "under 1 second" figure in 14.4 is the
// unconstrained number. If the real figure is 10 seconds, the infeasibility
// fallback ladder is the product rather than an edge case, and Phase 4 needs
// to know that before it is designed around the happy path.
//
// This is a cost probe, not the full 11.1 implementation: one target word per
// board rather than 1-3 families plus spaced-review families, and no fallback
// ladder. It answers the cost question and nothing else.

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::Generator;
using fluxcore::GenerationRecord;
using fluxcore::SeedPool;
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
    if (argc < 3) {
        std::cerr << "usage: genprobe <ruleset.json> <dawg> [boards-per-cell] [norm-boards]\n";
        return 1;
    }
    const std::string configPath = argv[1];
    const std::string dawgPath = argv[2];
    const uint32_t boardsPerCell = (argc > 3) ? static_cast<uint32_t>(std::stoul(argv[3])) : 40;
    const uint32_t normBoards = (argc > 4) ? static_cast<uint32_t>(std::stoul(argv[4])) : 400;

    fluxcore::config::LoadResult loaded;
    std::string error;
    if (!fluxcore::config::loadRulesetConfig(configPath, &loaded, &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }
    bool ok = false;
    const std::vector<uint8_t> bytes = readFile(dawgPath, &ok);
    if (!ok) { std::cerr << "error: cannot read " << dawgPath << "\n"; return 1; }
    Dawg dawg;
    if (!dawg.loadFromMemory(bytes.data(), bytes.size())) {
        std::cerr << "error: not a valid DAWG\n";
        return 1;
    }
    if (!fluxcore::config::enforceDictionary(loaded.config, dawg.sourceHash(), dawg.wordCount(),
                                             "genprobe")) {
        return 1;
    }

    SeedPool seeds;
    seeds.buildForRuleset(dawg, loaded.config);
    Generator generator(dawg, loaded.config, seeds);

    // Target stems: mid-length words, which is the band 7.5.1 says survives as
    // a teaching unit (-LLERS, -NTERS, -EATER, -ANTED).
    // Under a letter cap, a word over the cap is not a hard target but an
    // impossible one; counting it as infeasible would charge the generator
    // for the dictionary. (The v3 dictionary is already pruned of them.)
    std::vector<std::string> targets;
    char buf[64];
    uint32_t overCap = 0;
    for (uint32_t id = 0; id < dawg.wordCount() && targets.size() < 512; id += 523) {
        const size_t len = dawg.wordForId(id, buf, sizeof(buf));
        if (len < 5 || len > 6) continue;
        if (!fluxcore::fitsLetterCap(buf, static_cast<uint8_t>(len), loaded.config.maxPerLetter)) {
            ++overCap;
            continue;
        }
        targets.emplace_back(buf, len);
    }
    if (overCap > 0) std::printf("  skipped %u targets over the letter cap\n", overCap);
    if (targets.empty()) { std::cerr << "error: no target words found\n"; return 1; }

    std::printf("constrained generation cost probe (spec 11.1)\n");
    std::printf("  targets: %zu words of length 5-6; norm band = middle 80%% of %u unconstrained boards\n\n",
                targets.size(), normBoards);
    std::printf("  %-16s %10s %10s %9s %9s %8s %9s %10s\n", "cell", "normLow", "normHigh",
                "builds/bd", "solves/bd", "accept%", "infeas%", "ms/board");

    for (const uint8_t side : {4, 5}) {
        for (const Tier tier : {Tier::Casual, Tier::GoodCasual, Tier::Spam}) {
            // Establish the tier's norm band from unconstrained generation.
            std::vector<double> points;
            points.reserve(normBoards);
            Board board;
            GenerationRecord record;
            for (uint32_t i = 0; i < normBoards; ++i) {
                if (generator.generate(side, tier, i, 11, &board, &record)) {
                    points.push_back(static_cast<double>(record.winningPoints));
                }
            }
            if (points.empty()) continue;
            const Distribution norms = Distribution::from(points);
            const uint64_t low = static_cast<uint64_t>(norms.p10);
            const uint64_t high = static_cast<uint64_t>(norms.p90);

            uint64_t builds = 0, solves = 0, accepted = 0, infeasible = 0, produced = 0;
            const auto start = std::chrono::steady_clock::now();
            for (uint32_t i = 0; i < boardsPerCell; ++i) {
                const std::string& target = targets[i % targets.size()];
                Generator::ConstrainedStats stats;
                const bool okBoard = generator.generateConstrained(
                    side, tier, target.c_str(), static_cast<uint8_t>(target.size()), i, 11, low,
                    high, /*attemptBudget=*/20000, &board, &record, &stats);
                builds += stats.candidatesBuilt;
                solves += stats.solves;
                accepted += stats.candidatesAccepted;
                if (!okBoard) ++infeasible;
                ++produced;
            }
            const double seconds =
                std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();

            char cell[32];
            std::snprintf(cell, sizeof(cell), "%dx%d %s", side, side, tierName(tier));
            std::printf("  %-16s %10llu %10llu %9.1f %9.1f %7.1f%% %8.1f%% %10.1f\n", cell,
                        static_cast<unsigned long long>(low), static_cast<unsigned long long>(high),
                        static_cast<double>(builds) / produced,
                        static_cast<double>(solves) / produced,
                        100.0 * static_cast<double>(accepted) / static_cast<double>(builds ? builds : 1),
                        100.0 * static_cast<double>(infeasible) / produced,
                        1000.0 * seconds / produced);
        }
    }
    return 0;
}
