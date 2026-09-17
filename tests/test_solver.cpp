#include "solver.h"

#include "dawg_builder.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <fstream>
#include <map>
#include <random>
#include <set>
#include <string>
#include <vector>

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
using fluxcore::BoardGeometry;
using fluxcore::Dawg;
using fluxcore::ScoreTable;
using fluxcore::SolveMode;
using fluxcore::SolveResult;
using fluxcore::Solver;
using fluxcore::SolverOptions;
using namespace fluxcore::build;

namespace {

// The spec 2.2 table, written out literally so the test asserts against the
// spec rather than against whatever the config happens to say.
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

void checkSpecScoreTable() {
    const ScoreTable table = specScoreTable();
    CHECK(table.points(3) == 100);
    CHECK(table.points(4) == 400);
    CHECK(table.points(5) == 800);
    CHECK(table.points(6) == 1400);
    CHECK(table.points(7) == 1800);
    CHECK(table.points(8) == 2200);
    CHECK(table.points(9) == 2600);
}

Board makeBoard(uint8_t side, const std::string& letters) {
    Board board;
    board.side = side;
    for (size_t i = 0; i < letters.size(); ++i) {
        board.letters[i] = static_cast<uint8_t>(letters[i] - 'A');
    }
    return board;
}

std::vector<uint8_t> sortedDictionary(std::vector<std::string> words) {
    std::sort(words.begin(), words.end());
    words.erase(std::unique(words.begin(), words.end()), words.end());
    return serializeDawg(buildDawg(words));
}

std::map<std::string, uint32_t> wordsWithPathCounts(const Dawg& dawg, const SolveResult& result) {
    std::map<std::string, uint32_t> found;
    char buf[64];
    for (size_t i = 0; i < result.wordCount(); ++i) {
        const size_t len = dawg.wordForId(result.wordIds[i], buf, sizeof(buf));
        found[std::string(buf, len)] = result.pathCounts[i];
    }
    return found;
}

// 2x2, every cell adjacent to every other, so the expected answer is
// checkable by hand.
void testHandCheckedBoard() {
    std::vector<uint8_t> bytes = sortedDictionary({"CAT", "CATS", "ACT", "ACTS", "CAST", "SAT",
                                                   "TAS", "AT", "TA", "AS", "SA", "CATSUP"});
    Dawg dawg;
    CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));

    Solver solver(dawg, specScoreTable());
    SolveResult result;
    solver.solve(makeBoard(2, "CATS"), SolveMode::Full, &result);

    const auto found = wordsWithPathCounts(dawg, result);
    const std::set<std::string> expected = {"CAT", "CATS", "ACT", "ACTS", "CAST", "SAT", "TAS"};

    std::set<std::string> actual;
    for (const auto& [word, count] : found) {
        actual.insert(word);
        CHECK(count == 1);  // each spellable exactly one way on this board
    }
    CHECK(actual == expected);

    // AT / TA / AS / SA are in the dictionary but below minWordLen, and
    // CATSUP has no U or P on the board.
    CHECK(found.count("AT") == 0);
    CHECK(found.count("CATSUP") == 0);

    // 100 + 400 + 100 + 400 + 400 + 100 + 100
    CHECK(result.totalPoints == 1600);
    CHECK(result.wordsAtLeast5 == 0);
    CHECK(!result.pathCapHit);
}

// A word spellable along several paths is counted once in the potential
// metric and N times in pathCounts (spec 2.3).
void testMultiPathCountedOnce() {
    std::vector<uint8_t> bytes = sortedDictionary({"TAS"});
    Dawg dawg;
    CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));

    Solver solver(dawg, specScoreTable());
    SolveResult result;
    solver.solve(makeBoard(2, "TAAS"), SolveMode::Full, &result);

    CHECK(result.wordCount() == 1);
    CHECK(result.pathCounts[0] == 2);        // T-A-S through either A
    CHECK(result.storedPathCounts[0] == 2);
    CHECK(result.totalPoints == 100);        // ... but scored once
}

void testPathCapRecorded() {
    std::vector<uint8_t> bytes = sortedDictionary({"TAS"});
    Dawg dawg;
    CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));

    SolverOptions options;
    options.maxPathsPerWord = 1;
    Solver solver(dawg, specScoreTable(), options);
    SolveResult result;
    solver.solve(makeBoard(2, "TAAS"), SolveMode::Full, &result);

    CHECK(result.pathCounts[0] == 2);        // true count is still true
    CHECK(result.storedPathCounts[0] == 1);  // but only one was stored
    CHECK(result.pathCapHit);
    CHECK(result.pathCells.size() == 3);
}

// The invariants D6 asks for, checked over random boards against the real
// dictionary: no cell reused, every path actually spells its word, every
// consecutive pair is 8-way adjacent, and Count agrees with Full.
void testInvariants(const Dawg& dawg) {
    Solver solver(dawg, specScoreTable());
    SolveResult full, counted;
    std::mt19937 rng(20260917);
    std::uniform_int_distribution<int> letterDist(0, 25);
    char buf[64];

    for (int iteration = 0; iteration < 300; ++iteration) {
        const uint8_t side = (iteration % 2 == 0) ? 4 : 5;
        Board board;
        board.side = side;
        for (uint8_t c = 0; c < board.cellCount(); ++c) {
            board.letters[c] = static_cast<uint8_t>(letterDist(rng));
        }

        solver.solve(board, SolveMode::Full, &full);
        solver.solve(board, SolveMode::Count, &counted);

        // Count and Full must agree on the word set and the true path counts.
        CHECK(full.wordCount() == counted.wordCount());
        CHECK(full.totalPoints == counted.totalPoints);
        CHECK(full.wordsAtLeast5 == counted.wordsAtLeast5);
        std::map<uint32_t, uint32_t> countedPaths;
        for (size_t i = 0; i < counted.wordCount(); ++i) {
            countedPaths[counted.wordIds[i]] = counted.pathCounts[i];
        }

        const BoardGeometry& geom = solver.geometry(side);
        std::set<uint32_t> seenIds;

        for (size_t i = 0; i < full.wordCount(); ++i) {
            const uint32_t id = full.wordIds[i];
            CHECK(seenIds.insert(id).second);  // each word appears once in the SoA
            CHECK(countedPaths.count(id) == 1);
            CHECK(countedPaths[id] == full.pathCounts[i]);

            const size_t len = dawg.wordForId(id, buf, sizeof(buf));
            CHECK(len == full.wordLens[i]);
            CHECK(len >= solver.options().minWordLen);

            for (uint32_t p = 0; p < full.storedPathCounts[i]; ++p) {
                const uint8_t* cells = &full.pathCells[full.pathOffsets[i] + p * len];
                uint32_t used = 0;
                for (size_t k = 0; k < len; ++k) {
                    const uint8_t cell = cells[k];
                    CHECK(cell < board.cellCount());
                    CHECK((used & (1u << cell)) == 0);  // no tile reuse
                    used |= 1u << cell;
                    // the path actually spells the word
                    CHECK(board.letters[cell] == static_cast<uint8_t>(buf[k] - 'A'));
                    // adjacency is 8-way
                    if (k > 0) CHECK(geom.adjacent(cells[k - 1], cell));
                }
            }
        }
    }
}

// Cross-check against LetterCounter, which solved this board with a wholly
// independent trie solver during a 35M-board search and recorded both its
// score and its longest words in sim_summary.json. Agreement on the total
// exercises word enumeration, the count-once rule, the 2.2 score table and
// the adjacency rules at once.
void testKnownBoardAgainstLetterCounter(const Dawg& dawg) {
    Solver solver(dawg, specScoreTable());
    SolveResult result;
    solver.solve(makeBoard(4, "SEMCNAPAGIRSSELC"), SolveMode::Full, &result);

    CHECK(result.totalPoints == 834200);

    const std::vector<std::string> known = {
        "CAMPANILES", "CAMPAIGNS", "CAMPANILE", "CARELINES", "EMPARLING", "PEARLINGS",
        "SCRAPINGS",  "SPARLINGS", "SPEARINGS", "AMENAGES",  "CAMPAGNE",  "CAMPAIGN",
        "CAMPINGS",   "CARELINE",  "CARLINES",  "CARLINGS",  "CARPINGS",  "CARSPIEL",
        "CLINGERS",   "CRAMPING",  "EMAILERS",  "EMPAIRES",  "EMPARING",  "IGARAPES",
        "LINEAGES",   "MARLINES",  "MARLINGS",  "PARACMES",  "PEARLIES",  "PEARLING",
        "PEARLINS",   "PREGAMES",  "RAMPAGES",  "RAMPINGS",  "RASPINGS",  "SAMPIRES",
        "SARANGIS",   "SCRAPIES",  "SCRAPING",  "SEARINGS",  "SENARIES",  "SERINGAS",
        "SPARLING",   "SPEARING",  "SPINAGES",  "SPRINGES",  "AMENAGE",   "ASPINES",
        "ASPIRES",    "CAMAILS"};

    const auto found = wordsWithPathCounts(dawg, result);
    for (const std::string& word : known) {
        CHECK(found.count(word) == 1);
    }
}

std::vector<std::string> loadWordList(const std::string& path) {
    std::ifstream in(path);
    std::vector<std::string> words;
    if (!in) return words;
    std::string line;
    while (std::getline(in, line)) {
        while (!line.empty() && (line.back() == '\r' || std::isspace(static_cast<unsigned char>(line.back())))) {
            line.pop_back();
        }
        if (line.empty()) continue;
        for (char& c : line) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        if (!std::all_of(line.begin(), line.end(), [](char c) { return c >= 'A' && c <= 'Z'; })) continue;
        words.push_back(std::move(line));
    }
    std::sort(words.begin(), words.end());
    words.erase(std::unique(words.begin(), words.end()), words.end());
    return words;
}

}  // namespace

int main(int argc, char** argv) {
    checkSpecScoreTable();
    testHandCheckedBoard();
    testMultiPathCountedOnce();
    testPathCapRecorded();

    if (argc > 1) {
        const std::vector<std::string> words = loadWordList(argv[1]);
        if (words.empty()) {
            std::fprintf(stderr, "skip: could not load word list from %s\n", argv[1]);
        } else {
            std::vector<uint8_t> bytes = serializeDawg(buildDawg(words));
            Dawg dawg;
            CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));
            std::fprintf(stderr, "invariant test: %zu words\n", words.size());
            testInvariants(dawg);
            testKnownBoardAgainstLetterCounter(dawg);
        }
    } else {
        std::fprintf(stderr, "note: pass a word-list path as argv[1] to run the invariant test\n");
    }

    std::fprintf(stderr, "%d/%d checks passed\n", g_checks - g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
