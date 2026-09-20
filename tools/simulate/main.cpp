#include "config_json.h"
#include "generator.h"
#include "git_version.h"
#include "manifest.h"
#include "solver.h"
#include "stats.h"
#include "thread_pool.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

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

std::string cellName(uint8_t side, Tier tier) {
    return std::to_string(side) + "x" + std::to_string(side) + ":" + tierName(tier);
}

// One board's scalar outcome. Deliberately not a word list: spec 5.3 forbids
// accumulating per-board word lists, and these are what board_norms needs.
struct BoardRecord {
    uint32_t totalPoints = 0;
    uint32_t words = 0;
    uint32_t words5Plus = 0;
    uint32_t realizedN = 0;
    uint8_t seedLen = 0;
    bool seeded = false;
};

// Per-thread aggregates. Word counters are dense arrays indexed by word ID,
// which is exactly why D1 built a numbered DAWG.
struct ThreadAggregate {
    std::vector<uint32_t> boardsContaining;
    std::vector<uint64_t> pathTotal;
    std::vector<BoardRecord> records;
    uint64_t seededBoards = 0;
    uint64_t seededCandidates = 0;
    uint64_t totalCandidates = 0;
    uint64_t placementFailures = 0;

    void init(uint32_t words, size_t reserveBoards) {
        boardsContaining.assign(words, 0);
        pathTotal.assign(words, 0);
        records.reserve(reserveBoards);
    }
};

struct CellResult {
    uint8_t side = 0;
    Tier tier = Tier::Casual;
    uint64_t boards = 0;
    std::vector<uint32_t> boardsContaining;
    std::vector<uint64_t> pathTotal;
    std::vector<BoardRecord> records;
    uint64_t seededBoards = 0;
    uint64_t seededCandidates = 0;
    uint64_t totalCandidates = 0;
    uint64_t placementFailures = 0;
    double wallSeconds = 0;
};

std::vector<uint8_t> readFile(const std::string& path, bool* ok) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        *ok = false;
        return {};
    }
    *ok = true;
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

void usage() {
    std::cerr
        << "usage: simulate --config <ruleset.json> --dawg <file> --out <dir>\n"
        << "                [--boards-per-cell N] [--boards SIDExSIDE:TIER=N]...\n"
        << "                [--threads T] [--seed S]\n"
        << "  tiers: casual, goodCasual, spam    example: --boards 4x4:spam=20000\n";
}

}  // namespace

int main(int argc, char** argv) {
    std::string configPath, dawgPath, outDir;
    uint64_t boardsPerCell = 10000;
    uint64_t rootSeed = 1;
    unsigned threads = std::thread::hardware_concurrency();
    if (threads == 0) threads = 1;
    std::vector<std::pair<std::string, uint64_t>> overrides;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto next = [&](const char* what) -> std::string {
            if (i + 1 >= argc) {
                std::cerr << "error: " << what << " needs a value\n";
                std::exit(1);
            }
            return argv[++i];
        };
        if (arg == "--config") configPath = next("--config");
        else if (arg == "--dawg") dawgPath = next("--dawg");
        else if (arg == "--out") outDir = next("--out");
        else if (arg == "--boards-per-cell") boardsPerCell = std::stoull(next("--boards-per-cell"));
        else if (arg == "--seed") rootSeed = std::stoull(next("--seed"));
        else if (arg == "--threads") threads = static_cast<unsigned>(std::stoul(next("--threads")));
        else if (arg == "--boards") {
            const std::string spec = next("--boards");
            const size_t eq = spec.find('=');
            if (eq == std::string::npos) {
                std::cerr << "error: --boards wants CELL=N, got " << spec << "\n";
                return 1;
            }
            overrides.emplace_back(spec.substr(0, eq), std::stoull(spec.substr(eq + 1)));
        } else {
            usage();
            return 1;
        }
    }
    if (configPath.empty() || dawgPath.empty() || outDir.empty()) {
        usage();
        return 1;
    }

    fluxcore::config::LoadResult loaded;
    std::string error;
    if (!fluxcore::config::loadRulesetConfig(configPath, &loaded, &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }

    bool ok = false;
    const std::vector<uint8_t> dawgBytes = readFile(dawgPath, &ok);
    if (!ok) {
        std::cerr << "error: cannot read dawg: " << dawgPath << "\n";
        return 1;
    }
    Dawg dawg;
    if (!dawg.loadFromMemory(dawgBytes.data(), dawgBytes.size())) {
        std::cerr << "error: not a valid DAWG: " << dawgPath << "\n";
        return 1;
    }
    if (!fluxcore::config::enforceDictionary(loaded.config, dawg.sourceHash(), dawg.wordCount(),
                                             "simulate")) {
        return 1;
    }

    SeedPool seeds;
    seeds.buildForRuleset(dawg, loaded.config);

    std::vector<std::pair<uint8_t, Tier>> cells;
    for (uint8_t side : {4, 5}) {
        for (Tier tier : {Tier::Casual, Tier::GoodCasual, Tier::Spam}) cells.emplace_back(side, tier);
    }

    std::vector<uint64_t> cellBoards(cells.size(), boardsPerCell);
    for (const auto& [name, count] : overrides) {
        bool matched = false;
        for (size_t i = 0; i < cells.size(); ++i) {
            if (cellName(cells[i].first, cells[i].second) == name) {
                cellBoards[i] = count;
                matched = true;
            }
        }
        if (!matched) {
            std::cerr << "error: --boards names an unknown cell: " << name << "\n";
            return 1;
        }
    }

    std::fprintf(stderr, "simulate: ruleset v%u config %016llx, dictionary %u words, %u threads\n",
                 loaded.config.version, static_cast<unsigned long long>(loaded.config.configHash),
                 dawg.wordCount(), threads);
    if (!loaded.provisional.empty()) {
        std::fprintf(stderr, "  provisional:");
        for (const std::string& field : loaded.provisional) std::fprintf(stderr, " %s", field.c_str());
        std::fprintf(stderr, "\n");
    }

    const auto runStart = std::chrono::steady_clock::now();
    // Captured here, not at manifest-writing time: the field is named
    // startedUtc and a manifest that records the finish time under that
    // name misdescribes its own run.
    const std::string startedUtc = utcTimestamp();
    std::vector<CellResult> results;

    for (size_t c = 0; c < cells.size(); ++c) {
        const uint8_t side = cells[c].first;
        const Tier tier = cells[c].second;
        const uint64_t boards = cellBoards[c];
        if (boards == 0) continue;

        const std::string name = cellName(side, tier);
        const auto cellStart = std::chrono::steady_clock::now();

        std::vector<ThreadAggregate> perThread(threads);
        for (ThreadAggregate& agg : perThread) {
            agg.init(dawg.wordCount(), static_cast<size_t>(boards / threads + 1));
        }

        // One Generator and one Solver per worker: both hold scratch that is
        // allocated once and reused, and neither is thread-safe.
        std::vector<std::unique_ptr<Generator>> generators;
        std::vector<std::unique_ptr<Solver>> solvers;
        std::vector<SolveResult> scratch(threads);
        for (unsigned t = 0; t < threads; ++t) {
            generators.push_back(std::make_unique<Generator>(dawg, loaded.config, seeds));
            solvers.push_back(
                std::make_unique<Solver>(dawg, loaded.config.scores, loaded.config.solver));
        }

        parallelFor(
            boards, threads,
            [&](uint64_t index, unsigned t) {
                Board board;
                GenerationRecord record;
                if (!generators[t]->generate(side, tier, static_cast<uint32_t>(index), rootSeed,
                                             &board, &record)) {
                    return;
                }
                SolveResult& result = scratch[t];
                solvers[t]->solve(board, SolveMode::Count, &result);

                ThreadAggregate& agg = perThread[t];
                for (size_t i = 0; i < result.wordCount(); ++i) {
                    const uint32_t id = result.wordIds[i];
                    ++agg.boardsContaining[id];
                    agg.pathTotal[id] += result.pathCounts[i];
                }

                BoardRecord rec;
                rec.totalPoints = static_cast<uint32_t>(result.totalPoints);
                rec.words = static_cast<uint32_t>(result.wordCount());
                rec.words5Plus = result.wordsAtLeast5;
                rec.realizedN = record.realizedN;
                rec.seeded = record.seeded;
                rec.seedLen = record.seedLen;
                agg.records.push_back(rec);

                if (record.seeded) ++agg.seededBoards;
                agg.seededCandidates += record.seededCandidates;
                agg.totalCandidates += record.realizedN;
                agg.placementFailures += record.seedPlacementFailures;
            },
            [&](uint64_t done) {
                std::fprintf(stderr, "\r  %-16s %llu / %llu", name.c_str(),
                             static_cast<unsigned long long>(done),
                             static_cast<unsigned long long>(boards));
                std::fflush(stderr);
            });

        CellResult cell;
        cell.side = side;
        cell.tier = tier;
        cell.boards = boards;
        cell.boardsContaining.assign(dawg.wordCount(), 0);
        cell.pathTotal.assign(dawg.wordCount(), 0);
        for (ThreadAggregate& agg : perThread) {
            for (uint32_t w = 0; w < dawg.wordCount(); ++w) {
                cell.boardsContaining[w] += agg.boardsContaining[w];
                cell.pathTotal[w] += agg.pathTotal[w];
            }
            cell.records.insert(cell.records.end(), agg.records.begin(), agg.records.end());
            cell.seededBoards += agg.seededBoards;
            cell.seededCandidates += agg.seededCandidates;
            cell.totalCandidates += agg.totalCandidates;
            cell.placementFailures += agg.placementFailures;
        }
        cell.wallSeconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - cellStart).count();
        std::fprintf(stderr, "\r  %-16s %llu boards in %.1fs (%.0f boards/s)\n", name.c_str(),
                     static_cast<unsigned long long>(boards), cell.wallSeconds,
                     static_cast<double>(boards) / cell.wallSeconds);
        results.push_back(std::move(cell));
    }

    const double wallSeconds =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - runStart).count();

    // ---- outputs -----------------------------------------------------------

    std::ofstream wordStats(outDir + "/word_stats.tsv");
    std::ofstream boardNorms(outDir + "/board_norms.tsv");
    std::ofstream spamNorms(outDir + "/board_norms_by_n.tsv");
    if (!wordStats || !boardNorms || !spamNorms) {
        std::cerr << "\nerror: cannot write into " << outDir << " (does it exist?)\n";
        return 1;
    }

    wordStats << "grid\ttier\twordId\tword\tlen\tboards\tpAppear\tpathsPerBoard\n";
    // Spec 5.3: only words above about 1e-5 in a cell are worth keeping.
    constexpr double kRetainThreshold = 1e-5;
    char wordBuf[64];
    uint64_t retained = 0;

    boardNorms << distributionHeader("grid\ttier\tmetric") << "\tseededFrac\tmeanN\n";
    spamNorms << distributionHeader("grid\ttier\tnQuartile\tnMin\tnMax\tmetric") << "\n";

    for (const CellResult& cell : results) {
        const std::string grid = std::to_string(cell.side) + "x" + std::to_string(cell.side);

        for (uint32_t w = 0; w < cell.boardsContaining.size(); ++w) {
            if (cell.boardsContaining[w] == 0) continue;
            const double pAppear =
                static_cast<double>(cell.boardsContaining[w]) / static_cast<double>(cell.boards);
            if (pAppear < kRetainThreshold) continue;
            const size_t len = dawg.wordForId(w, wordBuf, sizeof(wordBuf));
            wordStats << grid << '\t' << tierName(cell.tier) << '\t' << w << '\t'
                      << std::string(wordBuf, len) << '\t' << len << '\t'
                      << cell.boardsContaining[w] << '\t' << pAppear << '\t'
                      << static_cast<double>(cell.pathTotal[w]) / static_cast<double>(cell.boards)
                      << '\n';
            ++retained;
        }

        std::vector<double> points, words, words5, ns;
        points.reserve(cell.records.size());
        words.reserve(cell.records.size());
        words5.reserve(cell.records.size());
        ns.reserve(cell.records.size());
        for (const BoardRecord& rec : cell.records) {
            points.push_back(rec.totalPoints);
            words.push_back(rec.words);
            words5.push_back(rec.words5Plus);
            ns.push_back(rec.realizedN);
        }
        const double seededFrac =
            static_cast<double>(cell.seededBoards) / static_cast<double>(cell.boards);
        const double meanN = Distribution::from(ns).mean;

        char tail[64];
        std::snprintf(tail, sizeof(tail), "\t%.4f\t%.1f", seededFrac, meanN);
        const std::string lead = grid + "\t" + tierName(cell.tier) + "\t";
        boardNorms << distributionRow(lead + "points", Distribution::from(points)) << tail << "\n";
        boardNorms << distributionRow(lead + "words", Distribution::from(words)) << tail << "\n";
        boardNorms << distributionRow(lead + "words5plus", Distribution::from(words5)) << tail
                   << "\n";

        // Spec 2.3/5.3: where N is a spread, curriculum-facing statistics are
        // also reported split at its quartiles, because averaging over the
        // draw hides that a board best-of-144 is a different board from
        // best-of-625.
        std::vector<double> sortedN = ns;
        std::sort(sortedN.begin(), sortedN.end());
        if (!sortedN.empty() && sortedN.front() != sortedN.back()) {
            for (int q = 0; q < 4; ++q) {
                const double lo = sortedN[static_cast<size_t>(q * 0.25 * (sortedN.size() - 1))];
                const double hi = sortedN[static_cast<size_t>((q + 1) * 0.25 * (sortedN.size() - 1))];
                std::vector<double> qp, qw, q5;
                for (const BoardRecord& rec : cell.records) {
                    if (rec.realizedN < lo || rec.realizedN > hi) continue;
                    qp.push_back(rec.totalPoints);
                    qw.push_back(rec.words);
                    q5.push_back(rec.words5Plus);
                }
                if (qp.empty()) continue;
                char qlead[128];
                std::snprintf(qlead, sizeof(qlead), "%s\t%s\tQ%d\t%.0f\t%.0f\t", grid.c_str(),
                              tierName(cell.tier), q + 1, lo, hi);
                spamNorms << distributionRow(std::string(qlead) + "points", Distribution::from(qp))
                          << "\n";
                spamNorms << distributionRow(std::string(qlead) + "words", Distribution::from(qw))
                          << "\n";
                spamNorms << distributionRow(std::string(qlead) + "words5plus",
                                             Distribution::from(q5))
                          << "\n";
            }
        }
    }

    Manifest manifest;
    manifest.tool = "simulate";
    manifest.outputDir = outDir;
    manifest.configPath = configPath;
    manifest.configHash = loaded.config.configHash;
    manifest.rulesetVersion = loaded.config.version;
    manifest.provisional = loaded.provisional;
    manifest.dictionaryPath = dawgPath;
    manifest.dictionaryHash = dawg.sourceHash();
    manifest.dictionaryWords = dawg.wordCount();
    manifest.gitSha = FLUX_GIT_SHA;
    manifest.gitDirty = FLUX_GIT_DIRTY;
    manifest.rootSeed = rootSeed;
    manifest.threads = threads;
    manifest.wallSeconds = wallSeconds;
    manifest.startedUtc = startedUtc;
    for (const CellResult& cell : results) {
        manifest.boardsPerCell.emplace_back(cellName(cell.side, cell.tier), cell.boards);
    }
    manifest.extra.emplace_back("retainThreshold", "1e-5");
    manifest.extra.emplace_back("wordStatsRows", std::to_string(retained));

    if (!writeManifest(manifest, outDir + "/manifest.json", &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }

    std::fprintf(stderr, "done in %.1fs; %llu word_stats rows -> %s\n", wallSeconds,
                 static_cast<unsigned long long>(retained), outDir.c_str());
    if (manifest.gitDirty) {
        std::fprintf(stderr,
                     "WARNING: working tree was dirty, so this run is not reproducible from its "
                     "git SHA alone.\n");
    }
    return 0;
}
