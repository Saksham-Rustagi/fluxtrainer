// Generation benchmark and cheap-scorer audit.
//
// For every (grid, tier) cell it generates the same boards twice -- once
// ranking candidates by a full solve, once by the truncated early-exit
// scorer -- and reports how often the two pick the same winner, along with
// the generation cost per board. The agreement number is the one that
// decides whether cheap scoring may be turned on at all: a scorer that
// changes the winner distribution silently biases every statistic built on
// best-of-N.

#include "config_json.h"
#include "generator.h"
#include "solver.h"

#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <thread>
#include <vector>

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::Generator;
using fluxcore::GenerationRecord;
using fluxcore::RulesetConfig;
using fluxcore::SeedPool;
using fluxcore::Tier;

namespace {

struct CellSpec {
    uint8_t side;
    Tier tier;
    uint32_t boards;
};

struct CellStats {
    uint32_t boards = 0;
    uint32_t agreements = 0;
    uint64_t fullNanos = 0;
    uint64_t cheapNanos = 0;
    uint64_t realizedN = 0;
    uint64_t candidatesScored = 0;
    uint64_t cheapAborts = 0;
    uint64_t fullPoints = 0;
    uint64_t cheapPoints = 0;
    uint32_t seededWinners = 0;
    uint64_t seededCandidates = 0;

    void merge(const CellStats& other) {
        boards += other.boards;
        agreements += other.agreements;
        fullNanos += other.fullNanos;
        cheapNanos += other.cheapNanos;
        realizedN += other.realizedN;
        candidatesScored += other.candidatesScored;
        cheapAborts += other.cheapAborts;
        fullPoints += other.fullPoints;
        cheapPoints += other.cheapPoints;
        seededWinners += other.seededWinners;
        seededCandidates += other.seededCandidates;
    }
};

const char* tierName(Tier tier) {
    switch (tier) {
        case Tier::Spam: return "Spam";
        case Tier::GoodCasual: return "GoodCasual";
        default: return "Casual";
    }
}

std::vector<uint8_t> readFile(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "error: cannot open %s\n", path.c_str());
        std::exit(1);
    }
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)),
                                std::istreambuf_iterator<char>());
}

void runRange(const Dawg& dawg, const RulesetConfig& fullConfig, const RulesetConfig& cheapConfig,
              const SeedPool& seeds, const CellSpec& cell, uint64_t rootSeed, uint32_t first,
              uint32_t last, CellStats* out) {
    Generator fullGen(dawg, fullConfig, seeds);
    Generator cheapGen(dawg, cheapConfig, seeds);

    Board fullBoard, cheapBoard;
    GenerationRecord fullRecord, cheapRecord;

    for (uint32_t i = first; i < last; ++i) {
        auto t0 = std::chrono::steady_clock::now();
        fullGen.generate(cell.side, cell.tier, i, rootSeed, &fullBoard, &fullRecord);
        auto t1 = std::chrono::steady_clock::now();
        cheapGen.generate(cell.side, cell.tier, i, rootSeed, &cheapBoard, &cheapRecord);
        auto t2 = std::chrono::steady_clock::now();

        ++out->boards;
        out->fullNanos += std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();
        out->cheapNanos += std::chrono::duration_cast<std::chrono::nanoseconds>(t2 - t1).count();
        out->realizedN += fullRecord.realizedN;
        out->candidatesScored += fullRecord.realizedN;
        out->cheapAborts += cheapRecord.cheapAborts;
        out->fullPoints += fullRecord.winningPoints;
        out->cheapPoints += cheapRecord.winningPoints;
        out->seededWinners += fullRecord.seeded ? 1u : 0u;
        out->seededCandidates += fullRecord.seededCandidates;

        const uint8_t cells = fullBoard.cellCount();
        if (std::memcmp(fullBoard.letters, cheapBoard.letters, cells) == 0) ++out->agreements;
    }
}

CellStats runCell(const Dawg& dawg, const RulesetConfig& fullConfig,
                  const RulesetConfig& cheapConfig, const SeedPool& seeds, const CellSpec& cell,
                  uint64_t rootSeed, uint32_t threads) {
    std::vector<CellStats> partials(threads);
    std::vector<std::thread> pool;
    const uint32_t chunk = (cell.boards + threads - 1) / threads;
    for (uint32_t t = 0; t < threads; ++t) {
        const uint32_t first = t * chunk;
        const uint32_t last = std::min(cell.boards, first + chunk);
        if (first >= last) continue;
        pool.emplace_back([&, t, first, last] {
            runRange(dawg, fullConfig, cheapConfig, seeds, cell, rootSeed, first, last,
                     &partials[t]);
        });
    }
    for (std::thread& thread : pool) thread.join();

    CellStats total;
    for (const CellStats& partial : partials) total.merge(partial);
    return total;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr,
                     "usage: genbench <ruleset.json> <dictionary.dawg> [scale] [marginPerMille] [threads]\n");
        return 1;
    }

    fluxcore::config::LoadResult loaded;
    std::string error;
    if (!fluxcore::config::loadRulesetConfig(argv[1], &loaded, &error)) {
        std::fprintf(stderr, "config error: %s\n", error.c_str());
        return 1;
    }

    const std::vector<uint8_t> dawgBytes = readFile(argv[2]);
    Dawg dawg;
    if (!dawg.loadFromMemory(dawgBytes.data(), dawgBytes.size())) {
        std::fprintf(stderr, "error: %s is not a valid DAWG\n", argv[2]);
        return 1;
    }
    if (!fluxcore::config::enforceDictionary(loaded.config, dawg.sourceHash(), dawg.wordCount(),
                                             "genbench")) {
        return 1;
    }

    const double scale = argc > 3 ? std::atof(argv[3]) : 1.0;

    RulesetConfig fullConfig = loaded.config;
    fullConfig.cheapScoringEnabled = false;
    RulesetConfig cheapConfig = loaded.config;
    cheapConfig.cheapScoringEnabled = true;
    if (argc > 4) cheapConfig.cheapScoringMarginPerMille = std::strtoul(argv[4], nullptr, 10);

    SeedPool seeds;
    seeds.buildForRuleset(dawg, loaded.config);

    std::printf("ruleset v%u  configHash %016llx  dictionary %u words  seed pool %zu words\n",
                loaded.config.version,
                static_cast<unsigned long long>(loaded.config.configHash), dawg.wordCount(),
                seeds.totalWords());
    std::printf("provisional fields:");
    for (const std::string& field : loaded.provisional) std::printf(" %s", field.c_str());
    std::printf("\ncheap scoring: minStartCells %u  marginPerMille %u\n\n",
                cheapConfig.cheapScoringMinStartCells, cheapConfig.cheapScoringMarginPerMille);

    // Sample sizes are per cell and deliberately uneven: a Spam board costs
    // two orders of magnitude more than a Casual one, and the agreement rate
    // needs volume where the boards are cheap.
    CellSpec cells[] = {
        {4, Tier::Casual, 2000},     {4, Tier::GoodCasual, 1500}, {4, Tier::Spam, 200},
        {5, Tier::Casual, 1000},     {5, Tier::GoodCasual, 400},  {5, Tier::Spam, 120},
    };

    uint32_t threads = argc > 5 ? static_cast<uint32_t>(std::strtoul(argv[5], nullptr, 10))
                                : std::thread::hardware_concurrency();
    if (threads == 0) threads = 1;
    const uint64_t rootSeed = 0x466C7578436F7265ull;  // "FluxCore"

    std::printf("%-5s %-11s %7s %8s %9s %9s %8s %8s %8s %8s %9s\n", "grid", "tier", "boards",
                "meanN", "full ms", "cheap ms", "speedup", "agree%", "abort%", "seed%", "points");

    CellStats overall;
    for (const CellSpec& spec : cells) {
        CellSpec scaled = spec;
        scaled.boards = static_cast<uint32_t>(spec.boards * scale);
        if (scaled.boards == 0) scaled.boards = 1;

        const CellStats stats =
            runCell(dawg, fullConfig, cheapConfig, seeds, scaled, rootSeed, threads);
        overall.merge(stats);

        const double boards = static_cast<double>(stats.boards);
        const double fullMs = stats.fullNanos / boards / 1e6;
        const double cheapMs = stats.cheapNanos / boards / 1e6;
        std::printf("%dx%d  %-11s %7u %8.1f %9.3f %9.3f %8.2f %8.2f %8.1f %8.1f %9.0f\n",
                    scaled.side, scaled.side, tierName(scaled.tier), stats.boards,
                    stats.realizedN / boards, fullMs, cheapMs,
                    cheapMs > 0 ? fullMs / cheapMs : 0.0,
                    100.0 * stats.agreements / boards,
                    100.0 * static_cast<double>(stats.cheapAborts) /
                        static_cast<double>(stats.candidatesScored),
                    100.0 * stats.seededWinners / boards,
                    static_cast<double>(stats.fullPoints) / boards);
        std::fflush(stdout);
    }

    const double boards = static_cast<double>(overall.boards);
    std::printf("\noverall: %u boards, agreement %.3f%%, speedup %.2fx\n", overall.boards,
                100.0 * overall.agreements / boards,
                overall.cheapNanos > 0
                    ? static_cast<double>(overall.fullNanos) / static_cast<double>(overall.cheapNanos)
                    : 0.0);
    std::printf("mean winning points: full %.0f, cheap %.0f (%.4f%% apart)\n",
                static_cast<double>(overall.fullPoints) / boards,
                static_cast<double>(overall.cheapPoints) / boards,
                overall.fullPoints == 0
                    ? 0.0
                    : 100.0 *
                          (static_cast<double>(overall.fullPoints) -
                           static_cast<double>(overall.cheapPoints)) /
                          static_cast<double>(overall.fullPoints));
    std::printf("base seed rate over candidates: %.2f%% (spec 2.3 says 50%%)\n",
                100.0 * static_cast<double>(overall.seededCandidates) /
                    static_cast<double>(overall.candidatesScored));
    return 0;
}
