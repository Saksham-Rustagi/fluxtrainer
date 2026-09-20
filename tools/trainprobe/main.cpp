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

// What a Phase 3 board costs to make, on the real stems and the real density
// band. genprobe answers spec 11.1's question -- the cost of a points-banded
// board at every tier. This answers Phase 3's, which is a different question
// with a different answer:
//
//   drill board        hook present, nothing else. No band at all.
//   acquisition board  hook present, plus a wide floor and ceiling on the
//                      board's distinct word count, 60% Casual / 40% Good
//                      Casual (spec 11.1), no Spam.
//
// The floor is the part that can bite. Embedding a stem pulls a board dense,
// so the ceiling is usually free and the floor is what rejects -- and on 4x4
// Casual the floor sits above the tier's own median, which is exactly the
// case the fallback ladder exists for. If a board costs more than about a
// second here, the app has to generate ahead rather than on demand.
//
//   trainprobe <ruleset.json> <dawg> <stems.txt> [boards-per-cell]
//
// stems.txt is one stem per line (cut -f2 reports/queue_hooks.tsv | tail -n +2).

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::Generator;
using fluxcore::GenerationRecord;
using fluxcore::SeedPool;
using fluxcore::SolveMode;
using fluxcore::Solver;
using fluxcore::SolveResult;
using fluxcore::Tier;
using namespace fluxtools;

namespace {

// hookrecord.py boardDensity: p10 and p95 of the player's own current-regime
// boards, per grid. Kept in step with the bundle by hand; the numbers are
// printed in the header so a drift is visible.
struct Band {
    uint8_t side;
    uint32_t minWords;
    uint32_t maxWords;
};
constexpr Band kBands[] = {{4, 238, 515}, {5, 469, 865}};

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
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)),
                                std::istreambuf_iterator<char>());
}

struct Row {
    std::string label;
    uint64_t builds = 0;
    uint64_t solves = 0;
    uint64_t produced = 0;
    uint64_t missing = 0;     // no board at all
    uint64_t exhausted = 0;   // a board, but short of the tier's best-of-N
    uint64_t wordRejects = 0;
    std::vector<double> ms;
    std::vector<double> words;
};

void report(const Row& r) {
    if (r.produced == 0) return;
    const Distribution ms = Distribution::from(r.ms);
    const Distribution words = Distribution::from(r.words);
    std::printf("  %-22s %8.1f %8.1f %9.0f %9.0f %8.1f%% %8.1f%% %9.0f\n", r.label.c_str(),
                static_cast<double>(r.builds) / r.produced,
                static_cast<double>(r.solves) / r.produced, ms.mean, ms.p90,
                100.0 * static_cast<double>(r.missing) / r.produced,
                100.0 * static_cast<double>(r.exhausted) / r.produced, words.mean);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::cerr << "usage: trainprobe <ruleset.json> <dawg> <stems.txt> [boards-per-cell]\n";
        return 1;
    }
    const uint32_t boardsPerCell = argc > 4 ? static_cast<uint32_t>(std::stoul(argv[4])) : 60;

    bool ok = false;
    const std::vector<uint8_t> dawgBytes = readFile(argv[2], &ok);
    if (!ok) { std::cerr << "error: cannot read " << argv[2] << "\n"; return 1; }
    const std::vector<uint8_t> configBytes = readFile(argv[1], &ok);
    if (!ok) { std::cerr << "error: cannot read " << argv[1] << "\n"; return 1; }

    Dawg dawg;
    if (!dawg.loadFromMemory(dawgBytes.data(), dawgBytes.size())) {
        std::cerr << "error: DAWG failed to load\n";
        return 1;
    }
    fluxcore::config::LoadResult loaded;
    std::string error;
    if (!fluxcore::config::parseRulesetConfig(
            reinterpret_cast<const char*>(configBytes.data()), configBytes.size(), argv[1],
            &loaded, &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }
    if (!fluxcore::config::checkDictionary(loaded.config, dawg.sourceHash(), dawg.wordCount(),
                                           &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }

    std::vector<std::string> stems;
    {
        std::ifstream in(argv[3]);
        std::string line;
        uint32_t overCap = 0;
        while (std::getline(in, line)) {
            while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) line.pop_back();
            if (line.size() < 3 || line.size() > 6) continue;
            if (!fluxcore::fitsLetterCap(line.c_str(), static_cast<uint8_t>(line.size()),
                                         loaded.config.maxPerLetter)) {
                ++overCap;
                continue;
            }
            stems.push_back(line);
        }
        if (overCap > 0) std::printf("  skipped %u stems over the letter cap\n", overCap);
    }
    if (stems.empty()) { std::cerr << "error: no stems\n"; return 1; }

    SeedPool seeds;
    seeds.buildForRuleset(dawg, loaded.config);
    Generator generator(dawg, loaded.config, seeds);
    Solver solver(dawg, loaded.config.scores, loaded.config.solver);
    SolveResult result;

    std::printf("Phase 3 board cost, %u boards a cell over %zu stems\n", boardsPerCell,
                stems.size());
    std::printf("  density band: 4x4 [%u, %u], 5x5 [%u, %u] (hookrecord.py boardDensity)\n\n",
                kBands[0].minWords, kBands[0].maxWords, kBands[1].minWords, kBands[1].maxWords);
    std::printf("  %-22s %8s %8s %9s %9s %9s %9s %9s\n", "board", "builds", "solves", "ms",
                "p90 ms", "missing", "short", "words");

    struct Case {
        const char* kind;
        uint8_t side;
        Tier tier;
        bool banded;
    };
    const Case cases[] = {
        {"drill", 4, Tier::GoodCasual, false},   {"drill", 5, Tier::GoodCasual, false},
        {"acquisition", 4, Tier::Casual, true},  {"acquisition", 4, Tier::GoodCasual, true},
        {"acquisition", 5, Tier::Casual, true},  {"acquisition", 5, Tier::GoodCasual, true},
    };

    for (const Case& c : cases) {
        const Band& band = c.side == 4 ? kBands[0] : kBands[1];
        Row row;
        char label[64];
        std::snprintf(label, sizeof(label), "%s %dx%d %s", c.kind, c.side, c.side,
                      tierName(c.tier));
        row.label = label;

        for (uint32_t i = 0; i < boardsPerCell; ++i) {
            const std::string& stem = stems[(i * 7919) % stems.size()];
            Board board;
            GenerationRecord record;
            Generator::ConstrainedStats stats;
            const auto t0 = std::chrono::steady_clock::now();
            const bool made = generator.generateConstrained(
                c.side, c.tier, stem.c_str(), static_cast<uint8_t>(stem.size()), 0,
                0x5EEDu + i, 0, ~0ull, /*attemptBudget=*/20000, &board, &record, &stats,
                c.banded ? band.minWords : 0, c.banded ? band.maxWords : 0);
            const double ms = std::chrono::duration<double, std::milli>(
                                  std::chrono::steady_clock::now() - t0)
                                  .count();
            ++row.produced;
            row.builds += stats.candidatesBuilt;
            row.solves += stats.solves;
            row.wordRejects += stats.wordRejects;
            row.ms.push_back(ms);
            if (stats.candidatesAccepted == 0) {
                ++row.missing;
                continue;
            }
            if (!made) ++row.exhausted;
            solver.solve(board, SolveMode::Count, &result);
            row.words.push_back(static_cast<double>(result.wordCount()));
        }
        report(row);
    }
    return 0;
}
