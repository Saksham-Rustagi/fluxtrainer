#include "generator.h"

#include "dawg_builder.h"
#include "solver.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <thread>
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
using fluxcore::Dawg;
using fluxcore::GenerationRecord;
using fluxcore::Generator;
using fluxcore::PotentialScorer;
using fluxcore::Rng;
using fluxcore::RulesetConfig;
using fluxcore::SeedPool;
using fluxcore::SolveMode;
using fluxcore::SolveResult;
using fluxcore::Solver;
using fluxcore::Tier;
using namespace fluxcore::build;

namespace {

constexpr uint64_t kRootSeed = 0x466C7578436F7265ull;

// The spec 2.2 and 2.3 tables written out literally, so the test asserts
// against the spec rather than against whatever config/ruleset_v1.json
// happens to say today.
RulesetConfig specConfig() {
    RulesetConfig config;
    config.version = 1;
    config.configHash = 0xABCDEF0123456789ull;

    for (uint8_t len = 0; len <= fluxcore::kMaxCells; ++len) {
        uint32_t points = 0;
        if (len == 3) points = 100;
        else if (len == 4) points = 400;
        else if (len == 5) points = 800;
        else if (len >= 6) points = 1400 + 400 * (len - 6);
        config.scores.pointsByLength[len] = points;
    }

    config.solver.minWordLen = 3;
    config.solver.maxPathsPerWord = 64;

    config.seedProbabilityPerMille = 500;
    config.extraSeedCount = 0;
    config.allowSeedOverlap = false;
    config.seedPathAttempts = 8;
    config.seedPlacementAttempts = 64;

    config.cheapScoringEnabled = false;
    config.cheapScoringMinStartCells = 8;
    config.cheapScoringMarginPerMille = 2500;

    fluxcore::GridConfig& g4 = config.grids[0];
    g4.side = 4;
    g4.share = 60;
    g4.tierShare[static_cast<uint8_t>(Tier::Spam)] = 20;
    g4.tierShare[static_cast<uint8_t>(Tier::GoodCasual)] = 50;
    g4.tierShare[static_cast<uint8_t>(Tier::Casual)] = 30;
    g4.candidates[static_cast<uint8_t>(Tier::Spam)] = {144, 625};
    g4.candidates[static_cast<uint8_t>(Tier::GoodCasual)] = {10, 20};
    g4.candidates[static_cast<uint8_t>(Tier::Casual)] = {5, 5};
    g4.seedLengths[0] = {8, 1, false};
    g4.seedLengths[1] = {9, 1, false};
    g4.seedLengths[2] = {10, 1, false};
    g4.seedLengths[3] = {11, 1, true};
    g4.seedLengthCount = 4;

    fluxcore::GridConfig& g5 = config.grids[1];
    g5.side = 5;
    g5.share = 40;
    g5.tierShare[static_cast<uint8_t>(Tier::Spam)] = 20;
    g5.tierShare[static_cast<uint8_t>(Tier::GoodCasual)] = 50;
    g5.tierShare[static_cast<uint8_t>(Tier::Casual)] = 30;
    g5.candidates[static_cast<uint8_t>(Tier::Spam)] = {81, 81};
    g5.candidates[static_cast<uint8_t>(Tier::GoodCasual)] = {10, 20};
    g5.candidates[static_cast<uint8_t>(Tier::Casual)] = {3, 3};
    g5.seedLengths[0] = {9, 1, false};
    g5.seedLengths[1] = {10, 1, false};
    g5.seedLengths[2] = {11, 1, false};
    g5.seedLengths[3] = {12, 1, false};
    g5.seedLengths[4] = {13, 1, true};
    g5.seedLengthCount = 5;

    config.gridCount = 2;
    return config;
}

void setLetterWeightsFromWords(const std::vector<std::string>& words, RulesetConfig* config) {
    for (uint8_t i = 0; i < 26; ++i) config->letterWeights[i] = 0;
    for (const std::string& word : words) {
        for (char c : word) ++config->letterWeights[c - 'A'];
    }
    for (uint8_t i = 0; i < 26; ++i) {
        if (config->letterWeights[i] == 0) config->letterWeights[i] = 1;
    }
}

std::vector<std::string> smallWordList() {
    return {"ACT", "ACTS", "CAST", "CAT", "CATS", "OAT", "OATS", "RAT",  "RATS",
            "SAT", "STAR", "TAR",  "TARS", "TAS", "TSAR", "COAT", "COATS", "COST",
            "COTS", "SCAT", "TACO", "TACOS", "ROAST", "ROASTS", "CARTS", "CART"};
}

std::vector<uint8_t> serializedDawg(std::vector<std::string> words) {
    std::sort(words.begin(), words.end());
    words.erase(std::unique(words.begin(), words.end()), words.end());
    return serializeDawg(buildDawg(words));
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
    std::sort(words.begin(), words.end());
    words.erase(std::unique(words.begin(), words.end()), words.end());
    return words;
}

// ---------------------------------------------------------------------------
// Tests that need no dictionary beyond a handful of words.
// ---------------------------------------------------------------------------

void testCanonicalForm() {
    Board board;
    board.side = 4;
    for (uint8_t c = 0; c < 16; ++c) board.letters[c] = static_cast<uint8_t>((c * 7 + 3) % 26);

    Board canonical;
    fluxcore::canonicalizeBoard(board, &canonical);
    const uint64_t hash = fluxcore::canonicalBoardHash(board);

    // Every dihedral image must canonicalize to the same board.
    for (uint8_t t = 0; t < 8; ++t) {
        Board image;
        image.side = 4;
        for (uint8_t r = 0; r < 4; ++r) {
            for (uint8_t c = 0; c < 4; ++c) {
                uint8_t sr = r, sc = c;
                const uint8_t n = 3;
                switch (t) {
                    case 1: sr = c; sc = n - r; break;
                    case 2: sr = n - r; sc = n - c; break;
                    case 3: sr = n - c; sc = r; break;
                    case 4: sr = r; sc = n - c; break;
                    case 5: sr = n - r; sc = c; break;
                    case 6: sr = c; sc = r; break;
                    case 7: sr = n - c; sc = n - r; break;
                    default: break;
                }
                image.letters[r * 4 + c] = board.letters[sr * 4 + sc];
            }
        }
        Board imageCanonical;
        fluxcore::canonicalizeBoard(image, &imageCanonical);
        CHECK(std::memcmp(canonical.letters, imageCanonical.letters, 16) == 0);
        CHECK(fluxcore::canonicalBoardHash(image) == hash);
    }

    Board other = board;
    other.letters[5] = static_cast<uint8_t>((other.letters[5] + 1) % 26);
    CHECK(fluxcore::canonicalBoardHash(other) != hash);
}

// The realized N is a uniform draw over the tier's range (spec 2.3) and is
// recorded per board (spec 5.3), so board_norms can aggregate over it the way
// ranked does.
void testRealizedNUniform(const Dawg& dawg, const SeedPool& seeds) {
    RulesetConfig config = specConfig();
    setLetterWeightsFromWords(smallWordList(), &config);
    config.seedProbabilityPerMille = 0;

    Generator generator(dawg, config, seeds);
    Board board;
    GenerationRecord record;

    const uint32_t boards = 600;
    const uint32_t low = 144, high = 625;
    const uint32_t buckets = 6;
    std::vector<uint32_t> counts(buckets, 0);
    uint64_t sum = 0;
    uint32_t minSeen = high, maxSeen = low;

    for (uint32_t i = 0; i < boards; ++i) {
        CHECK(generator.generate(4, Tier::Spam, i, kRootSeed, &board, &record));
        CHECK(record.realizedN >= low);
        CHECK(record.realizedN <= high);
        sum += record.realizedN;
        minSeen = std::min(minSeen, record.realizedN);
        maxSeen = std::max(maxSeen, record.realizedN);
        const uint32_t bucket = (record.realizedN - low) * buckets / (high - low + 1);
        ++counts[bucket];
    }

    const double mean = static_cast<double>(sum) / boards;
    CHECK(mean > 365.0 && mean < 405.0);  // uniform mean is 384.5
    CHECK(minSeen < low + 40);
    CHECK(maxSeen > high - 40);
    for (uint32_t b = 0; b < buckets; ++b) {
        // 100 expected per bucket, sd 9.1; +-5 sd is a wide but real check
        CHECK(counts[b] > 55 && counts[b] < 145);
    }

    // The 5x5 Spam cell is a point, not a range, and must come back exactly.
    CHECK(generator.generate(5, Tier::Spam, 0, kRootSeed, &board, &record));
    CHECK(record.realizedN == 81);
}

// Byte-identical output from the same root seed, and output that does not
// depend on which worker produced a board or in what order. The stream is
// derived from the board index rather than the thread index precisely so
// that thread count cannot leak into the results.
void testReproducibility(const Dawg& dawg, const SeedPool& seeds) {
    RulesetConfig config = specConfig();
    setLetterWeightsFromWords(smallWordList(), &config);
    config.grids[0].candidates[static_cast<uint8_t>(Tier::Spam)] = {20, 40};
    config.grids[1].candidates[static_cast<uint8_t>(Tier::Spam)] = {20, 20};

    const uint32_t boards = 120;
    const Tier tiers[] = {Tier::Casual, Tier::GoodCasual, Tier::Spam};

    std::map<std::pair<uint32_t, uint32_t>, Board> reference;
    std::map<std::pair<uint32_t, uint32_t>, GenerationRecord> records;
    {
        Generator generator(dawg, config, seeds);
        Board board;
        GenerationRecord record;
        for (uint8_t side : {4, 5}) {
            for (Tier tier : tiers) {
                for (uint32_t i = 0; i < boards; ++i) {
                    CHECK(generator.generate(side, tier, i, kRootSeed, &board, &record));
                    const auto key = std::make_pair(
                        fluxcore::simulationCellId(side, tier), i);
                    reference[key] = board;
                    records[key] = record;
                }
            }
        }
    }

    // Same seed, fresh generator, same bytes.
    {
        Generator generator(dawg, config, seeds);
        Board board;
        GenerationRecord record;
        for (const auto& [key, expected] : reference) {
            const uint8_t side = expected.side;
            const Tier tier = records.at(key).tier;
            CHECK(generator.generate(side, tier, key.second, kRootSeed, &board, &record));
            CHECK(board.side == expected.side);
            CHECK(std::memcmp(board.letters, expected.letters, board.cellCount()) == 0);
            CHECK(record.realizedN == records.at(key).realizedN);
            CHECK(record.winningPoints == records.at(key).winningPoints);
            CHECK(record.seeded == records.at(key).seeded);
        }
    }

    // A different root seed has to move the boards, or "reproducible" would
    // be indistinguishable from "constant".
    {
        Generator generator(dawg, config, seeds);
        Board board;
        GenerationRecord record;
        uint32_t different = 0;
        for (uint32_t i = 0; i < boards; ++i) {
            CHECK(generator.generate(4, Tier::Casual, i, kRootSeed + 1, &board, &record));
            const auto key = std::make_pair(fluxcore::simulationCellId(4, Tier::Casual), i);
            if (std::memcmp(board.letters, reference.at(key).letters, 16) != 0) ++different;
        }
        CHECK(different > boards - 5);
    }

    // Thread count must not change a single byte. Each worker takes a strided
    // subset, so both the worker count and the per-worker board order differ
    // from the sequential run.
    for (uint32_t threads : {2u, 7u}) {
        std::vector<std::vector<std::pair<std::pair<uint32_t, uint32_t>, Board>>> produced(threads);
        std::vector<std::thread> pool;
        for (uint32_t t = 0; t < threads; ++t) {
            pool.emplace_back([&, t] {
                Generator generator(dawg, config, seeds);
                Board board;
                GenerationRecord record;
                for (uint8_t side : {4, 5}) {
                    for (Tier tier : tiers) {
                        for (uint32_t i = t; i < boards; i += threads) {
                            generator.generate(side, tier, i, kRootSeed, &board, &record);
                            produced[t].push_back(
                                {{fluxcore::simulationCellId(side, tier), i}, board});
                        }
                    }
                }
            });
        }
        for (std::thread& thread : pool) thread.join();

        size_t compared = 0;
        for (const auto& partial : produced) {
            for (const auto& [key, board] : partial) {
                const Board& expected = reference.at(key);
                CHECK(std::memcmp(board.letters, expected.letters, board.cellCount()) == 0);
                ++compared;
            }
        }
        CHECK(compared == reference.size());
    }
}

// ---------------------------------------------------------------------------
// Tests that need the real dictionary.
// ---------------------------------------------------------------------------

// The truncated scorer must agree with the solver exactly when it runs to
// completion; only the early exit may ever change an outcome.
void testScorerMatchesSolver(const Dawg& dawg, const RulesetConfig& config) {
    Solver solver(dawg, config.scores, config.solver);
    PotentialScorer scorer(dawg, config);
    SolveResult result;
    Rng rng(12345);

    for (int iteration = 0; iteration < 200; ++iteration) {
        const uint8_t side = (iteration % 2 == 0) ? 4 : 5;
        Board board;
        board.side = side;
        for (uint8_t c = 0; c < board.cellCount(); ++c) {
            board.letters[c] =
                static_cast<uint8_t>(rng.pickWeighted(config.letterWeights, 26,
                                                      config.letterWeightTotal()));
        }

        solver.solve(board, SolveMode::Count, &result);
        bool aborted = true;
        const uint64_t points = scorer.score(board, solver.geometry(side), 0, &aborted);
        CHECK(!aborted);
        CHECK(points == result.totalPoints);
    }
}

// Spec 2.3: 50% of boards carry a seed. The rate is a property of the
// candidates, not of the winners -- selection runs after seeding and pushes
// seeded boards up the ranking -- so it is measured with best-of-1, where
// the winner is an ordinary candidate.
void testSeedRateAndLengths(const Dawg& dawg, const SeedPool& seeds, const RulesetConfig& base) {
    RulesetConfig config = base;
    for (uint8_t g = 0; g < config.gridCount; ++g) {
        for (uint8_t t = 0; t < fluxcore::kTierCount; ++t) {
            config.grids[g].candidates[t] = {1, 1};
        }
    }

    Generator generator(dawg, config, seeds);
    Board board;
    GenerationRecord record;
    Solver solver(dawg, config.scores, config.solver);
    SolveResult result;

    struct CellCounts {
        uint32_t boards = 0;
        uint32_t seeded = 0;
        std::map<uint8_t, uint32_t> lengths;
    };
    std::map<std::pair<uint8_t, uint8_t>, CellCounts> counts;

    const Tier tiers[] = {Tier::Casual, Tier::GoodCasual, Tier::Spam};
    for (uint8_t side : {4, 5}) {
        const uint32_t boards = side == 4 ? 1200u : 500u;
        for (Tier tier : tiers) {
            CellCounts& cell = counts[{side, static_cast<uint8_t>(tier)}];
            for (uint32_t i = 0; i < boards; ++i) {
                CHECK(generator.generate(side, tier, i, kRootSeed, &board, &record));
                ++cell.boards;
                CHECK(record.seedPlacementFailures == 0);
                if (!record.seeded) continue;
                ++cell.seeded;
                ++cell.lengths[record.seedLen];

                // The seed has to be on the board, which is the only check
                // that the self-avoiding walk placement is actually valid.
                if (i % 40 == 0) {
                    solver.solve(board, SolveMode::Count, &result);
                    CHECK(std::find(result.wordIds.begin(), result.wordIds.end(),
                                    record.seedWordId) != result.wordIds.end());
                }
            }
        }
    }

    uint32_t totalBoards = 0, totalSeeded = 0;
    for (const auto& [key, cell] : counts) {
        totalBoards += cell.boards;
        totalSeeded += cell.seeded;

        const uint8_t side = key.first;
        const Tier tier = static_cast<Tier>(key.second);
        for (const auto& [length, count] : cell.lengths) {
            CHECK(count > 0);
            if (side == 4) {
                CHECK(length >= 8 && length <= 11);
                if (tier != Tier::Spam) CHECK(length != 11);  // longest is Spam-only
            } else {
                CHECK(length >= 9 && length <= 13);
                if (tier != Tier::Spam) CHECK(length != 13);
            }
        }
        // Every allowed length must actually show up, or a length option is
        // silently dead.
        const uint8_t expectedLengths = (tier == Tier::Spam) ? (side == 4 ? 4 : 5)
                                                             : (side == 4 ? 3 : 4);
        CHECK(cell.lengths.size() == expectedLengths);
    }

    const double rate = static_cast<double>(totalSeeded) / totalBoards;
    CHECK(rate > 0.46 && rate < 0.54);  // spec 2.3: 50%
}

// Spec 2.3 / 5.3: the tiers are a best-of-N ladder over the same candidate
// distribution, so their mean potential has to come out ordered.
void testTierOrdering(const Dawg& dawg, const SeedPool& seeds, const RulesetConfig& config) {
    Generator generator(dawg, config, seeds);
    Board board;
    GenerationRecord record;

    for (uint8_t side : {4, 5}) {
        double mean[fluxcore::kTierCount] = {};
        const uint32_t boards = side == 4 ? 40u : 25u;
        for (uint8_t t = 0; t < fluxcore::kTierCount; ++t) {
            uint64_t total = 0;
            for (uint32_t i = 0; i < boards; ++i) {
                CHECK(generator.generate(side, static_cast<Tier>(t), i, kRootSeed, &board,
                                         &record));
                total += record.winningPoints;
                CHECK(record.winningCandidate < record.realizedN);
                CHECK(record.seededCandidates <= record.realizedN);
                CHECK(record.configHash == config.configHash);
                CHECK(record.rulesetVersion == config.version);
            }
            mean[t] = static_cast<double>(total) / boards;
        }
        std::fprintf(stderr, "  %dx%d mean potential: casual %.0f, good casual %.0f, spam %.0f\n",
                     side, side, mean[0], mean[1], mean[2]);
        CHECK(mean[static_cast<uint8_t>(Tier::Spam)] >
              mean[static_cast<uint8_t>(Tier::GoodCasual)]);
        CHECK(mean[static_cast<uint8_t>(Tier::GoodCasual)] >
              mean[static_cast<uint8_t>(Tier::Casual)]);
    }
}

// Best-of-N is a maximum: the winner's points must be the best of the
// candidates, and turning the cheap scorer on must not raise them.
void testWinnerIsTheMaximum(const Dawg& dawg, const SeedPool& seeds, const RulesetConfig& base) {
    RulesetConfig config = base;
    config.grids[0].candidates[static_cast<uint8_t>(Tier::GoodCasual)] = {12, 12};

    Generator generator(dawg, config, seeds);
    RulesetConfig single = config;
    single.grids[0].candidates[static_cast<uint8_t>(Tier::GoodCasual)] = {1, 1};

    Board board;
    GenerationRecord record;
    for (uint32_t i = 0; i < 25; ++i) {
        CHECK(generator.generate(4, Tier::GoodCasual, i, kRootSeed, &board, &record));
        CHECK(record.realizedN == 12);

        // Rebuilding candidate 0 alone must reproduce the first candidate's
        // score, which pins the per-candidate stream derivation.
        Generator singleGen(dawg, single, seeds);
        Board first;
        GenerationRecord firstRecord;
        CHECK(singleGen.generate(4, Tier::GoodCasual, i, kRootSeed, &first, &firstRecord));
        CHECK(record.winningPoints >= firstRecord.winningPoints);
        if (record.winningCandidate == 0) {
            CHECK(std::memcmp(board.letters, first.letters, 16) == 0);
        }
    }

    RulesetConfig cheap = config;
    cheap.cheapScoringEnabled = true;
    Generator cheapGen(dawg, cheap, seeds);
    Board cheapBoard;
    GenerationRecord cheapRecord;
    for (uint32_t i = 0; i < 25; ++i) {
        CHECK(generator.generate(4, Tier::GoodCasual, i, kRootSeed, &board, &record));
        CHECK(cheapGen.generate(4, Tier::GoodCasual, i, kRootSeed, &cheapBoard, &cheapRecord));
        CHECK(cheapRecord.realizedN == record.realizedN);
        CHECK(cheapRecord.winningPoints <= record.winningPoints);
    }
}

}  // namespace

int main(int argc, char** argv) {
    testCanonicalForm();

    {
        const std::vector<uint8_t> bytes = serializedDawg(smallWordList());
        Dawg dawg;
        CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));
        SeedPool seeds;  // no seed words at these lengths; seeding is off in these tests
        testRealizedNUniform(dawg, seeds);
        testReproducibility(dawg, seeds);
    }

    if (argc > 1) {
        const std::vector<std::string> words = loadWordList(argv[1]);
        if (words.empty()) {
            std::fprintf(stderr, "skip: could not load word list from %s\n", argv[1]);
        } else {
            const std::vector<uint8_t> bytes = serializeDawg(buildDawg(words));
            Dawg dawg;
            CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));

            RulesetConfig config = specConfig();
            setLetterWeightsFromWords(words, &config);

            SeedPool seeds;
            seeds.buildForRuleset(dawg, config);
            std::fprintf(stderr, "generator tests: %zu words, %zu seed words\n", words.size(),
                         seeds.totalWords());
            CHECK(seeds.totalWords() > 0);
            CHECK(seeds.hasLength(8) && seeds.hasLength(13));

            testScorerMatchesSolver(dawg, config);
            testSeedRateAndLengths(dawg, seeds, config);
            testTierOrdering(dawg, seeds, config);
            testWinnerIsTheMaximum(dawg, seeds, config);
        }
    } else {
        std::fprintf(stderr, "note: pass a word-list path as argv[1] to run the seeded tests\n");
    }

    std::fprintf(stderr, "%d/%d checks passed\n", g_checks - g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
