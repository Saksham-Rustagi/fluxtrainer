#include "solver.h"

#include "dawg_builder.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <map>
#include <random>
#include <set>
#include <string>
#include <unordered_set>
#include <vector>

// Brute-force differential oracle (build prompt D6, spec 2.1 / 5.2).
//
// Everything below re-derives the rules from scratch: 8-way adjacency is
// recomputed inline from row/column arithmetic rather than through
// BoardGeometry, the dictionary is a flat hash set rather than the DAWG, and
// there is no prefix pruning of any kind. A bug shared between the oracle and
// the solver is the one thing this test cannot catch, so the oracle shares
// nothing with it.

namespace {

int g_checks = 0;
int g_failures = 0;

}  // namespace

#define CHECK(cond)                                                                         \
    do {                                                                                    \
        ++g_checks;                                                                         \
        if (!(cond)) {                                                                      \
            ++g_failures;                                                                   \
            std::fprintf(stderr, "CHECK FAILED at %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        }                                                                                   \
    } while (0)

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::ScoreTable;
using fluxcore::SolveMode;
using fluxcore::SolveResult;
using fluxcore::Solver;
using fluxcore::SolverOptions;
using namespace fluxcore::build;

namespace {

// ---------------------------------------------------------------------------
// Knobs
// ---------------------------------------------------------------------------

// Boards per (grid size, letter pool) pair. There are 8 such pairs, so the
// total board count is 8x this.
constexpr int kBoardsPerConfig = 40;

// No path longer than this is explored, and the dictionary is filtered to
// words of at most this length. The filter is what keeps the comparison
// exact: with no dictionary word longer than the cap, there is nothing the
// solver could find that the oracle declined to look for.
constexpr size_t kMaxPathLen = 7;

constexpr uint8_t kMinWordLen = 3;  // spec 2.2 scores from 3
constexpr uint32_t kSeed = 20260917;

// Effectively uncapped, so storedPathCounts == pathCounts and the stored
// paths themselves can be compared against the oracle's. The capped
// behaviour is checked separately in testPathCapAgainstOracle().
constexpr uint32_t kUncappedPathStore = 1u << 24;

// Per board, to keep a genuine divergence readable instead of a wall of text.
constexpr int kMaxReportedMismatches = 6;

// ---------------------------------------------------------------------------
// The oracle
// ---------------------------------------------------------------------------

struct Oracle {
    std::map<std::string, std::set<std::vector<uint8_t>>> found;
    uint64_t pathsExplored = 0;
};

void oracleRecurse(const Board& board, const std::unordered_set<std::string>& dict, uint8_t cell,
                   std::string& word, std::vector<uint8_t>& path, std::vector<char>& used,
                   Oracle& out) {
    word.push_back(static_cast<char>('A' + board.letters[cell]));
    path.push_back(cell);
    used[cell] = 1;
    ++out.pathsExplored;

    if (word.size() >= kMinWordLen && dict.count(word) != 0) {
        out.found[word].insert(path);
    }

    if (word.size() < kMaxPathLen) {
        const int side = board.side;
        const int row = cell / side;
        const int col = cell % side;
        for (uint8_t next = 0; next < board.cellCount(); ++next) {
            if (used[next]) continue;
            const int dr = (next / side) - row;
            const int dc = (next % side) - col;
            if (dr < -1 || dr > 1 || dc < -1 || dc > 1) continue;
            oracleRecurse(board, dict, next, word, path, used, out);
        }
    }

    used[cell] = 0;
    path.pop_back();
    word.pop_back();
}

Oracle runOracle(const Board& board, const std::unordered_set<std::string>& dict) {
    Oracle out;
    std::string word;
    std::vector<uint8_t> path;
    std::vector<char> used(board.cellCount(), 0);
    word.reserve(kMaxPathLen);
    path.reserve(kMaxPathLen);
    for (uint8_t cell = 0; cell < board.cellCount(); ++cell) {
        oracleRecurse(board, dict, cell, word, path, used, out);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

ScoreTable specScoreTable() {
    ScoreTable table;
    for (uint8_t len = 0; len <= fluxcore::kMaxCells; ++len) {
        uint32_t points = 0;
        if (len == 3) points = 100;
        else if (len == 4) points = 400;
        else if (len == 5) points = 800;
        else if (len >= 6) points = 1400 + 400 * (len - 6);
        table.pointsByLength[len] = points;
    }
    return table;
}

std::vector<std::string> normalize(std::vector<std::string> words) {
    std::vector<std::string> kept;
    for (std::string& w : words) {
        if (w.empty() || w.size() > kMaxPathLen) continue;
        kept.push_back(std::move(w));
    }
    std::sort(kept.begin(), kept.end());
    kept.erase(std::unique(kept.begin(), kept.end()), kept.end());
    return kept;
}

// Real words over a deliberately narrow alphabet, plus 2-letter entries that
// the solver must refuse to report even though the DAWG holds them.
std::vector<std::string> realWordDictionary() {
    return normalize({"AE",     "AR",     "AS",     "AT",     "EA",     "ER",     "ES",
                      "ET",     "RE",     "SA",     "ST",     "TA",     "TE",     "AAS",
                      "ARE",    "ARS",    "ART",    "ATE",    "EAR",    "EAS",    "EAT",
                      "ERA",    "ERS",    "EST",    "ETA",    "RAT",    "RES",    "RET",
                      "SAE",    "SAT",    "SEA",    "SER",    "SET",    "STAR",   "TAE",
                      "TAR",    "TAS",    "TAT",    "TEA",    "TES",    "TET",    "AREA",
                      "AREAS",  "ARES",   "ARTS",   "ATES",   "EARS",   "EAST",   "EATS",
                      "ERAS",   "ERST",   "ESTS",   "ETAS",   "RATE",   "RATS",   "REST",
                      "RETS",   "SATE",   "SEAR",   "SEAS",   "SEAT",   "SERA",   "STAT",
                      "STET",   "TARE",   "TARS",   "TART",   "TATE",   "TEAR",   "TEAS",
                      "TEAT",   "TEST",   "TETS",   "TREAT",  "TSAR",   "ARETE",  "ASTER",
                      "EATER",  "ESTER",  "RATES",  "RESAT",  "RESET",  "SATES",  "STARE",
                      "START",  "STATE",  "STEAR",  "TARES",  "TARTS",  "TASTE",  "TATER",
                      "TEARS",  "TEASE",  "TERAS",  "TESTA",  "TREAT",  "TREATS", "ARREST",
                      "ASSERT", "ASTERS", "EASTER", "ESTATE", "RATTER", "RESEAT", "SEATER",
                      "STATER", "STATES", "TASTER", "TATTER", "TEASER", "TESTAE", "ESTATES",
                      "RETASTE", "STARTER", "TASTERS", "TATTERS", "TEASERS"});
}

// A dense random dictionary over a tiny alphabet. Real words are too sparse to
// exercise the multi-path bookkeeping hard; this produces boards where the
// same word is spellable dozens of ways.
std::vector<std::string> syntheticDictionary(std::mt19937& rng, const std::string& alphabet,
                                             size_t count) {
    std::uniform_int_distribution<size_t> letterDist(0, alphabet.size() - 1);
    std::uniform_int_distribution<size_t> lenDist(2, kMaxPathLen);
    std::vector<std::string> words;
    words.reserve(count);
    for (size_t i = 0; i < count; ++i) {
        std::string w(lenDist(rng), 'A');
        for (char& c : w) c = alphabet[letterDist(rng)];
        words.push_back(std::move(w));
    }
    return normalize(std::move(words));
}

struct Dictionary {
    std::string name;
    std::vector<uint8_t> bytes;
    std::unordered_set<std::string> words;
};

Dictionary makeDictionary(const std::string& name, const std::vector<std::string>& sortedWords) {
    Dictionary dict;
    dict.name = name;
    dict.bytes = serializeDawg(buildDawg(sortedWords));
    dict.words.insert(sortedWords.begin(), sortedWords.end());
    return dict;
}

struct BoardConfig {
    const char* name;
    uint8_t side;
    std::string alphabet;
    // Cells drawn from the first two letters of the alphabet with this
    // probability, which is what produces the heavily repeated boards.
    double repeatBias;
};

Board randomBoard(std::mt19937& rng, const BoardConfig& config) {
    std::uniform_int_distribution<size_t> letterDist(0, config.alphabet.size() - 1);
    std::uniform_real_distribution<double> biasDist(0.0, 1.0);
    Board board;
    board.side = config.side;
    for (uint8_t c = 0; c < board.cellCount(); ++c) {
        char letter;
        if (biasDist(rng) < config.repeatBias) {
            letter = config.alphabet[letterDist(rng) % 2];
        } else {
            letter = config.alphabet[letterDist(rng)];
        }
        board.letters[c] = static_cast<uint8_t>(letter - 'A');
    }
    return board;
}

// ---------------------------------------------------------------------------
// Comparison
// ---------------------------------------------------------------------------

void printBoard(const Board& board) {
    std::fprintf(stderr, "  board %dx%d:\n", board.side, board.side);
    for (uint8_t r = 0; r < board.side; ++r) {
        std::fprintf(stderr, "    ");
        for (uint8_t c = 0; c < board.side; ++c) {
            std::fprintf(stderr, "%c ", 'A' + board.letters[r * board.side + c]);
        }
        std::fprintf(stderr, "\n");
    }
    std::string flat;
    for (uint8_t c = 0; c < board.cellCount(); ++c) flat.push_back('A' + board.letters[c]);
    std::fprintf(stderr, "    reproduce with makeBoard(%d, \"%s\")\n", board.side, flat.c_str());
}

struct SolverView {
    std::map<std::string, uint32_t> pathCounts;
    std::map<std::string, std::set<std::vector<uint8_t>>> storedPaths;
    std::map<std::string, uint8_t> lens;
};

SolverView viewOf(const Dawg& dawg, const SolveResult& result, bool withPaths) {
    SolverView view;
    char buf[64];
    for (size_t i = 0; i < result.wordCount(); ++i) {
        const size_t len = dawg.wordForId(result.wordIds[i], buf, sizeof(buf));
        const std::string word(buf, len);
        view.pathCounts[word] = result.pathCounts[i];
        view.lens[word] = result.wordLens[i];
        if (!withPaths) continue;
        auto& paths = view.storedPaths[word];
        for (uint32_t p = 0; p < result.storedPathCounts[i]; ++p) {
            const uint8_t* cells = &result.pathCells[result.pathOffsets[i] + p * len];
            paths.insert(std::vector<uint8_t>(cells, cells + len));
        }
    }
    return view;
}

// Returns the number of divergences found on this board.
int compareOneBoard(const Board& board, const Oracle& oracle, const Dawg& dawg,
                    const SolveResult& full, bool comparePaths) {
    const SolverView view = viewOf(dawg, full, comparePaths);
    int mismatches = 0;
    int reported = 0;

    auto report = [&](const char* what, const std::string& word, long long expected,
                      long long actual) {
        ++mismatches;
        if (reported++ >= kMaxReportedMismatches) return;
        std::fprintf(stderr, "ORACLE MISMATCH (%s): word \"%s\" oracle=%lld solver=%lld\n", what,
                     word.c_str(), expected, actual);
        printBoard(board);
    };

    for (const auto& entry : oracle.found) {
        const auto it = view.pathCounts.find(entry.first);
        if (it == view.pathCounts.end()) {
            report("word missing from solver", entry.first,
                   static_cast<long long>(entry.second.size()), 0);
            continue;
        }
        if (it->second != entry.second.size()) {
            report("path count", entry.first, static_cast<long long>(entry.second.size()),
                   it->second);
        }
        if (view.lens.at(entry.first) != entry.first.size()) {
            report("word length", entry.first, static_cast<long long>(entry.first.size()),
                   view.lens.at(entry.first));
        }
        if (comparePaths) {
            const auto& stored = view.storedPaths.at(entry.first);
            if (stored != entry.second) {
                report("path set", entry.first, static_cast<long long>(entry.second.size()),
                       static_cast<long long>(stored.size()));
            }
        }
    }

    for (const auto& entry : view.pathCounts) {
        if (oracle.found.count(entry.first) == 0) {
            report("word not on board", entry.first, 0, entry.second);
        }
    }

    uint64_t expectedPoints = 0;
    uint32_t expectedAtLeast5 = 0;
    const ScoreTable scores = specScoreTable();
    for (const auto& entry : oracle.found) {
        expectedPoints += scores.points(static_cast<uint8_t>(entry.first.size()));
        if (entry.first.size() >= 5) ++expectedAtLeast5;
    }
    if (full.totalPoints != expectedPoints) {
        ++mismatches;
        std::fprintf(stderr, "ORACLE MISMATCH (totalPoints): oracle=%llu solver=%llu\n",
                     static_cast<unsigned long long>(expectedPoints),
                     static_cast<unsigned long long>(full.totalPoints));
        printBoard(board);
    }
    if (full.wordsAtLeast5 != expectedAtLeast5) {
        ++mismatches;
        std::fprintf(stderr, "ORACLE MISMATCH (wordsAtLeast5): oracle=%u solver=%u\n",
                     expectedAtLeast5, full.wordsAtLeast5);
        printBoard(board);
    }
    return mismatches;
}

struct RunStats {
    int boards = 0;
    uint64_t paths = 0;
    uint64_t words = 0;
    uint64_t wordPaths = 0;
    uint64_t multiPathWords = 0;
    uint32_t maxPathsForOneWord = 0;
};

void runDifferential(const Dictionary& dict, const std::vector<BoardConfig>& configs, int perConfig,
                     RunStats& stats) {
    Dawg dawg;
    CHECK(dawg.loadFromMemory(dict.bytes.data(), dict.bytes.size()));

    SolverOptions options;
    options.minWordLen = kMinWordLen;
    options.maxPathsPerWord = kUncappedPathStore;
    Solver solver(dawg, specScoreTable(), options);

    SolveResult full, counted;
    std::mt19937 rng(kSeed);

    for (const BoardConfig& config : configs) {
        int divergences = 0;
        for (int i = 0; i < perConfig; ++i) {
            const Board board = randomBoard(rng, config);
            const Oracle oracle = runOracle(board, dict.words);

            solver.solve(board, SolveMode::Full, &full);
            divergences += compareOneBoard(board, oracle, dawg, full, /*comparePaths=*/true);
            CHECK(!full.pathCapHit);  // the comparison above assumes nothing was truncated

            // Count mode must agree with Full on everything it reports.
            solver.solve(board, SolveMode::Count, &counted);
            divergences += compareOneBoard(board, oracle, dawg, counted, /*comparePaths=*/false);

            ++stats.boards;
            stats.paths += oracle.pathsExplored;
            stats.words += oracle.found.size();
            for (const auto& entry : oracle.found) {
                const uint32_t n = static_cast<uint32_t>(entry.second.size());
                stats.wordPaths += n;
                if (n > 1) ++stats.multiPathWords;
                stats.maxPathsForOneWord = std::max(stats.maxPathsForOneWord, n);
            }
        }
        CHECK(divergences == 0);
        if (divergences != 0) {
            std::fprintf(stderr, "  ^ %d divergence(s) on %s / %s\n", divergences,
                         dict.name.c_str(), config.name);
        }
    }
}

// The capped path store must truncate what it keeps without corrupting the
// true count, so the oracle checks both halves of that promise at once.
void testPathCapAgainstOracle(const Dictionary& dict, const BoardConfig& config, int boards) {
    Dawg dawg;
    CHECK(dawg.loadFromMemory(dict.bytes.data(), dict.bytes.size()));

    SolverOptions options;
    options.minWordLen = kMinWordLen;
    options.maxPathsPerWord = 3;
    Solver solver(dawg, specScoreTable(), options);

    SolveResult result;
    std::mt19937 rng(kSeed + 1);
    int mismatches = 0;
    bool sawCapHit = false;

    for (int i = 0; i < boards; ++i) {
        const Board board = randomBoard(rng, config);
        const Oracle oracle = runOracle(board, dict.words);
        solver.solve(board, SolveMode::Full, &result);

        const SolverView view = viewOf(dawg, result, /*withPaths=*/true);
        bool expectCapHit = false;
        char buf[64];
        for (size_t w = 0; w < result.wordCount(); ++w) {
            const size_t len = dawg.wordForId(result.wordIds[w], buf, sizeof(buf));
            const std::string word(buf, len);
            const auto it = oracle.found.find(word);
            if (it == oracle.found.end()) {
                ++mismatches;
                std::fprintf(stderr, "ORACLE MISMATCH (capped run, word not on board): \"%s\"\n",
                             word.c_str());
                printBoard(board);
                continue;
            }
            const uint32_t trueCount = static_cast<uint32_t>(it->second.size());
            if (trueCount > options.maxPathsPerWord) expectCapHit = true;

            if (result.pathCounts[w] != trueCount) {
                ++mismatches;
                std::fprintf(stderr,
                             "ORACLE MISMATCH (capped run, pathCounts): \"%s\" oracle=%u solver=%u\n",
                             word.c_str(), trueCount, result.pathCounts[w]);
                printBoard(board);
            }
            const uint32_t expectedStored = std::min(trueCount, options.maxPathsPerWord);
            if (result.storedPathCounts[w] != expectedStored) {
                ++mismatches;
                std::fprintf(stderr,
                             "ORACLE MISMATCH (capped run, storedPathCounts): \"%s\" expected=%u "
                             "solver=%u\n",
                             word.c_str(), expectedStored, result.storedPathCounts[w]);
                printBoard(board);
            }
            // Whatever survived truncation must still be a real path.
            const auto& stored = view.storedPaths.at(word);
            for (const auto& path : stored) {
                if (it->second.count(path) == 0) {
                    ++mismatches;
                    std::fprintf(stderr, "ORACLE MISMATCH (capped run, bogus path): \"%s\"\n",
                                 word.c_str());
                    printBoard(board);
                }
            }
        }
        if (result.pathCapHit != expectCapHit) {
            ++mismatches;
            std::fprintf(stderr, "ORACLE MISMATCH (pathCapHit): oracle=%d solver=%d\n",
                         static_cast<int>(expectCapHit), static_cast<int>(result.pathCapHit));
            printBoard(board);
        }
        sawCapHit = sawCapHit || expectCapHit;
    }
    CHECK(mismatches == 0);
    CHECK(sawCapHit);  // otherwise this test proved nothing
}

std::vector<BoardConfig> boardConfigs() {
    return {
        {"3x3 uniform ARESTL", 3, "ARESTL", 0.0},
        {"3x3 four letters ARES", 3, "ARES", 0.0},
        {"3x3 heavy repeats", 3, "ARESTL", 0.6},
        {"4x4 uniform ARESTL", 4, "ARESTL", 0.0},
        {"4x4 four letters ARES", 4, "ARES", 0.0},
        {"4x4 heavy repeats", 4, "ARESTL", 0.6},
        {"4x4 two letters AE", 4, "AE", 0.0},
        {"4x4 QU no special case", 4, "QUAEIT", 0.25},
    };
}

std::vector<std::string> loadWordList(const std::string& path) {
    std::ifstream in(path);
    std::vector<std::string> words;
    if (!in) return words;
    std::string line;
    while (std::getline(in, line)) {
        while (!line.empty() &&
               (line.back() == '\r' || std::isspace(static_cast<unsigned char>(line.back())))) {
            line.pop_back();
        }
        if (line.empty()) continue;
        for (char& c : line) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        if (!std::all_of(line.begin(), line.end(), [](char c) { return c >= 'A' && c <= 'Z'; })) {
            continue;
        }
        words.push_back(std::move(line));
    }
    return normalize(std::move(words));
}

void printStats(const char* label, const RunStats& stats, double seconds) {
    std::fprintf(stderr,
                 "%s: %d boards, %llu paths enumerated, %llu word hits (%llu word-paths, "
                 "%llu multi-path words, max %u paths for one word), %.2fs\n",
                 label, stats.boards, static_cast<unsigned long long>(stats.paths),
                 static_cast<unsigned long long>(stats.words),
                 static_cast<unsigned long long>(stats.wordPaths),
                 static_cast<unsigned long long>(stats.multiPathWords), stats.maxPathsForOneWord,
                 seconds);
}

}  // namespace

int main(int argc, char** argv) {
    const auto start = std::chrono::steady_clock::now();
    std::mt19937 dictRng(kSeed);

    const Dictionary realDict = makeDictionary("real words", realWordDictionary());
    const Dictionary denseDict =
        makeDictionary("synthetic dense", syntheticDictionary(dictRng, "ARESTL", 1200));
    const Dictionary tinyAlphabetDict =
        makeDictionary("synthetic AEQU", syntheticDictionary(dictRng, "AEQU", 400));

    const std::vector<BoardConfig> configs = boardConfigs();

    RunStats stats;
    runDifferential(realDict, configs, kBoardsPerConfig, stats);
    runDifferential(denseDict, configs, kBoardsPerConfig, stats);
    runDifferential(tinyAlphabetDict, configs, kBoardsPerConfig, stats);
    printStats("differential", stats,
               std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count());

    testPathCapAgainstOracle(denseDict, configs[3], 20);

    if (argc > 1) {
        const std::vector<std::string> words = loadWordList(argv[1]);
        if (words.empty()) {
            std::fprintf(stderr, "skip: could not load word list from %s\n", argv[1]);
        } else {
            const auto bigStart = std::chrono::steady_clock::now();
            const Dictionary big = makeDictionary("full dictionary", words);
            std::fprintf(stderr, "full-dictionary oracle run: %zu words of length <= %zu\n",
                         words.size(), kMaxPathLen);
            RunStats bigStats;
            runDifferential(big, configs, kBoardsPerConfig / 2, bigStats);
            printStats("full dictionary", bigStats,
                       std::chrono::duration<double>(std::chrono::steady_clock::now() - bigStart)
                           .count());
        }
    } else {
        std::fprintf(stderr,
                     "note: pass a word-list path as argv[1] to also run the oracle against the "
                     "full dictionary\n");
    }

    const double elapsed =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    std::fprintf(stderr, "%d/%d checks passed in %.2fs\n", g_checks - g_failures, g_checks,
                 elapsed);
    return g_failures == 0 ? 0 : 1;
}
