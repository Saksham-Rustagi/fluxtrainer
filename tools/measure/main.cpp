#include "affix.h"
#include "config_json.h"
#include "generator.h"
#include "git_version.h"
#include "lexicon.h"
#include "manifest.h"
#include "solver.h"
#include "stats.h"
#include "thread_pool.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

// D5: the three measurements Phase 1 exists to produce.
//
//   M1 reachability     P(additive extension has a path that extends the
//                       stem's path | stem path present), by mined affix and
//                       stem length. The free-vocabulary thesis (3.5) rests
//                       on this, and 15 makes it the gate for Phases 3 and 4.
//   M2 cellmate         P(anagram has a valid path | word has a valid path)
//                       by length, plus drop-interior. Drop-terminal is NOT
//                       measured -- it is P = 1.0 by construction (7.6) and
//                       is counted instead.
//   M3 enumerability    E[distinct family members findable | stem present],
//                       per tier and stem length, for 7.5's 2-to-6 band.

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::Generator;
using fluxcore::GenerationRecord;
using fluxcore::SeedPool;
using fluxcore::SolveMode;
using fluxcore::SolveResult;
using fluxcore::Solver;
using fluxcore::Tier;
using namespace fluxcore::lex;
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

// ---------------------------------------------------------------------------
// Candidate sets. Bounded deliberately: the build prompt says a few thousand
// stems is plenty for a decision and not to try to be exhaustive.
// ---------------------------------------------------------------------------

struct M1Stem {
    uint32_t wordId = 0;
    uint8_t len = 0;
    // Extensions of this stem, as (word id, offset of the stem inside it).
    std::vector<std::pair<uint32_t, uint8_t>> extensions;
    std::vector<uint16_t> affixIndex;  // parallel to extensions; mined affix, or 0xFFFF
};

// M3 is measured over two stem populations, because which one you sample
// decides the answer. `broad` strides the whole family index and is what the
// first Phase 1 report used. `curated` is the population a real curriculum
// would draw from: stems ranked by productivity, meaning the number of
// distinct valid completions they have in CSW21 weighted by the points those
// completions score, top few thousand per stem length.
// Two curated depths rather than one, because "curate harder" is a lever the
// curriculum can actually pull: if the tight set beats the wide one, depth is
// a gradient and 7.5's cutoff can be bought with a shorter stem list.
//
// `curatedWord` applies the identical ranking to stems that are themselves
// valid words. It exists because the unrestricted ranking turns out to select
// morphological tails -- TION, NESS, ATIO, SSES -- which are legitimate
// hunting cues but are not what 7.5 means by a stem to teach. If the two
// curated columns disagree, the curriculum implication differs by which
// population it draws from, and the report has to say which.
constexpr size_t kSampleCount = 4;
constexpr size_t kBroad = 0;
constexpr size_t kCurated = 1;
constexpr size_t kCuratedTight = 2;
constexpr size_t kCuratedWord = 3;
const char* const kSampleNames[kSampleCount] = {"broad", "curated", "curatedTight", "curatedWord"};

// Per-(stem, affix) tallies. Two conditionings are reported because the spec
// does not disambiguate them and they differ: per-PATH is the honest
// free-points number (your finger is on that path), per-BOARD is the upper
// bound (some path of the stem admits the extension).
struct ReachTally {
    uint64_t stemPaths = 0;       // stem paths observed
    uint64_t pathHits = 0;        // ... that admitted this extension
    uint64_t stemBoards = 0;      // boards where the stem had any path
    uint64_t boardHits = 0;       // ... where some stem path admitted it
};

struct CellTallies {
    // M1
    std::vector<ReachTally> byAffix;     // indexed by mined affix
    std::vector<ReachTally> byStemLen;   // indexed by stem length
    ReachTally overall;
    uint64_t foundWords = 0;
    uint64_t m1StemInstances = 0;   // found words that are sampled M1 stems
    uint64_t reachableExtensions = 0;
    uint64_t distinctFreeWords = 0;  // distinct extension words reachable, per board
    uint64_t boardsWithStems = 0;

    // M2
    std::vector<uint64_t> anagramTrials, anagramHits;    // by word length
    std::vector<uint64_t> interiorTrials, interiorHits;  // by word length
    uint64_t dropTerminalImplied = 0;                    // P = 1.0, counted not measured
    uint64_t dropTerminalBoards = 0;
    uint64_t dropTerminalSourceWords = 0;
    uint64_t boardsForCellmates = 0;

    // M3, tallied once per stem sample (see kSampleNames). The broad sample
    // and the curated one are measured on the SAME boards in the same pass,
    // so the difference between the two tables is curation and nothing else.
    //
    // memberSum counts every findable family member; memberSumOther excludes
    // the stem itself. The two differ only for stems that ARE words, where
    // the stem is a member of its own family and is found whenever it has a
    // path -- a guaranteed 1 that a fragment stem like ATIO can never score.
    // Comparing a word-stem sample against a fragment sample on memberSum
    // alone would credit curation with that floor, so memberSumOther is the
    // honest column: what ELSE the stem gets you, which is what 7.5 is asking.
    struct M3Tally {
        std::vector<uint64_t> stemPresent, memberSum, memberSumOther;  // by stem length
        std::vector<uint64_t> stemPresentQ[4], memberSumQ[4], memberSumOtherQ[4];  // by N quartile

        void init() {
            stemPresent.assign(kMaxStemLen + 1, 0);
            memberSum.assign(kMaxStemLen + 1, 0);
            memberSumOther.assign(kMaxStemLen + 1, 0);
            for (int q = 0; q < 4; ++q) {
                stemPresentQ[q].assign(kMaxStemLen + 1, 0);
                memberSumQ[q].assign(kMaxStemLen + 1, 0);
                memberSumOtherQ[q].assign(kMaxStemLen + 1, 0);
            }
        }

        void merge(const M3Tally& other) {
            for (size_t i = 0; i < stemPresent.size(); ++i) {
                stemPresent[i] += other.stemPresent[i];
                memberSum[i] += other.memberSum[i];
                memberSumOther[i] += other.memberSumOther[i];
                for (int q = 0; q < 4; ++q) {
                    stemPresentQ[q][i] += other.stemPresentQ[q][i];
                    memberSumQ[q][i] += other.memberSumQ[q][i];
                    memberSumOtherQ[q][i] += other.memberSumOtherQ[q][i];
                }
            }
        }
    };
    M3Tally m3[kSampleCount];

    void init(size_t affixes) {
        byAffix.assign(affixes, {});
        byStemLen.assign(fluxcore::kMaxCells + 1, {});
        anagramTrials.assign(fluxcore::kMaxCells + 1, 0);
        anagramHits.assign(fluxcore::kMaxCells + 1, 0);
        interiorTrials.assign(fluxcore::kMaxCells + 1, 0);
        interiorHits.assign(fluxcore::kMaxCells + 1, 0);
        for (M3Tally& tally : m3) tally.init();
    }

    void merge(const CellTallies& other) {
        auto addReach = [](ReachTally& a, const ReachTally& b) {
            a.stemPaths += b.stemPaths; a.pathHits += b.pathHits;
            a.stemBoards += b.stemBoards; a.boardHits += b.boardHits;
        };
        for (size_t i = 0; i < byAffix.size(); ++i) addReach(byAffix[i], other.byAffix[i]);
        for (size_t i = 0; i < byStemLen.size(); ++i) addReach(byStemLen[i], other.byStemLen[i]);
        addReach(overall, other.overall);
        foundWords += other.foundWords;
        m1StemInstances += other.m1StemInstances;
        reachableExtensions += other.reachableExtensions;
        distinctFreeWords += other.distinctFreeWords;
        boardsWithStems += other.boardsWithStems;
        for (size_t i = 0; i < anagramTrials.size(); ++i) {
            anagramTrials[i] += other.anagramTrials[i];
            anagramHits[i] += other.anagramHits[i];
            interiorTrials[i] += other.interiorTrials[i];
            interiorHits[i] += other.interiorHits[i];
        }
        dropTerminalImplied += other.dropTerminalImplied;
        dropTerminalBoards += other.dropTerminalBoards;
        dropTerminalSourceWords += other.dropTerminalSourceWords;
        boardsForCellmates += other.boardsForCellmates;
        for (size_t s = 0; s < kSampleCount; ++s) m3[s].merge(other.m3[s]);
    }
};

// Does `stem` have a valid path on this board? Used for M3, where stems are
// arbitrary substrings rather than words, so the solver's output cannot
// answer it. Letter-count prefilter first: most stems fail on letters alone.
bool stemHasPath(const Board& board, const fluxcore::BoardGeometry& geom, const char* stem,
                 uint8_t len, const uint8_t* boardLetterCounts) {
    if (len == 0 || len > board.cellCount()) return false;
    uint8_t need[26] = {};
    for (uint8_t i = 0; i < len; ++i) {
        const uint8_t c = static_cast<uint8_t>(stem[i] - 'A');
        if (++need[c] > boardLetterCounts[c]) return false;
    }

    // Iterative DFS over (cell, depth, visited).
    struct Frame { uint8_t cell; uint8_t depth; uint32_t visited; uint8_t next; };
    Frame stack[fluxcore::kMaxCells + 1];

    for (uint8_t start = 0; start < board.cellCount(); ++start) {
        if (board.letters[start] != static_cast<uint8_t>(stem[0] - 'A')) continue;
        if (len == 1) return true;
        int top = 0;
        stack[0] = {start, 1, 1u << start, 0};
        while (top >= 0) {
            Frame& frame = stack[top];
            const uint8_t count = geom.neighborCount(frame.cell);
            if (frame.next >= count) { --top; continue; }
            const uint8_t next = geom.neighbors(frame.cell)[frame.next++];
            if (frame.visited & (1u << next)) continue;
            if (board.letters[next] != static_cast<uint8_t>(stem[frame.depth] - 'A')) continue;
            if (frame.depth + 1 == len) return true;
            stack[top + 1] = {next, static_cast<uint8_t>(frame.depth + 1),
                              frame.visited | (1u << next), 0};
            ++top;
        }
    }
    return false;
}

}  // namespace

int main(int argc, char** argv) {
    std::string configPath, dawgPath, outDir;
    uint64_t boardsPerCell = 4000;
    uint64_t rootSeed = 1;
    uint32_t stemBudget = 3000;
    uint32_t curatedPerLen = 2000;
    uint32_t curatedTight = 500;
    unsigned threads = std::thread::hardware_concurrency();
    if (threads == 0) threads = 1;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto next = [&](const char* what) -> std::string {
            if (i + 1 >= argc) { std::cerr << "error: " << what << " needs a value\n"; std::exit(1); }
            return argv[++i];
        };
        if (arg == "--config") configPath = next("--config");
        else if (arg == "--dawg") dawgPath = next("--dawg");
        else if (arg == "--out") outDir = next("--out");
        else if (arg == "--boards-per-cell") boardsPerCell = std::stoull(next("--boards-per-cell"));
        else if (arg == "--seed") rootSeed = std::stoull(next("--seed"));
        else if (arg == "--stems") stemBudget = static_cast<uint32_t>(std::stoul(next("--stems")));
        else if (arg == "--curated-per-len")
            curatedPerLen = static_cast<uint32_t>(std::stoul(next("--curated-per-len")));
        else if (arg == "--curated-tight")
            curatedTight = static_cast<uint32_t>(std::stoul(next("--curated-tight")));
        else if (arg == "--threads") threads = static_cast<unsigned>(std::stoul(next("--threads")));
        else {
            std::cerr << "usage: measure --config <f> --dawg <f> --out <dir> "
                         "[--boards-per-cell N] [--stems N] [--curated-per-len N] "
                         "[--curated-tight N] [--threads T] [--seed S]\n";
            return 1;
        }
    }
    if (configPath.empty() || dawgPath.empty() || outDir.empty()) {
        std::cerr << "error: --config, --dawg and --out are required\n";
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
    if (!ok) { std::cerr << "error: cannot read " << dawgPath << "\n"; return 1; }
    Dawg dawg;
    if (!dawg.loadFromMemory(dawgBytes.data(), dawgBytes.size())) {
        std::cerr << "error: not a valid DAWG\n";
        return 1;
    }

    const auto runStart = std::chrono::steady_clock::now();
    // See the note in simulate: this is the run's start, not the manifest's.
    const std::string startedUtc = utcTimestamp();
    std::fprintf(stderr, "measure: building lexicon indices...\n");

    SubwordIndex subwords;
    subwords.build(dawg, SubwordOptions{});
    AnagramIndex anagrams;
    anagrams.build(dawg);
    MinedAffixSet mined;
    mined.build(dawg, subwords, MinedAffixOptions{});
    FamilyOptions familyOptions;
    familyOptions.minStemLen = 2;
    familyOptions.maxStemLen = kMaxStemLen;
    StemFamilyIndex families;
    if (!families.build(dawg, familyOptions, &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }

    // Mined affix lookup: affix text -> index, for reporting M1 by affix.
    std::vector<std::string> affixNames;
    std::unordered_map<std::string, uint16_t> affixIds;
    for (const MinedAffix& affix : mined.back()) {
        affixIds["-" + std::string(affix.letters, affix.len)] =
            static_cast<uint16_t>(affixNames.size());
        affixNames.push_back("-" + std::string(affix.letters, affix.len));
    }
    for (const MinedAffix& affix : mined.front()) {
        affixIds[std::string(affix.letters, affix.len) + "-"] =
            static_cast<uint16_t>(affixNames.size());
        affixNames.push_back(std::string(affix.letters, affix.len) + "-");
    }

    // --- M1 candidate stems: bounded, stratified by length ------------------
    std::vector<M1Stem> m1Stems;
    std::vector<uint32_t> m1SlotOf(dawg.wordCount(), 0xFFFFFFFFu);
    {
        std::vector<uint32_t> perLen(fluxcore::kMaxCells + 1, 0);
        const uint32_t perLenCap = stemBudget / 6 + 1;
        char stemBuf[64], wordBuf[64];
        for (uint32_t id = 0; id < dawg.wordCount() && m1Stems.size() < stemBudget; ++id) {
            const size_t stemLen = dawg.wordForId(id, stemBuf, sizeof(stemBuf));
            if (stemLen < 3 || stemLen > 8) continue;
            if (perLen[stemLen] >= perLenCap) continue;
            uint32_t count = 0;
            const AdditiveExtension* extensions = subwords.extensionsForStem(id, &count);
            if (count == 0) continue;

            M1Stem stem;
            stem.wordId = id;
            stem.len = static_cast<uint8_t>(stemLen);
            for (uint32_t e = 0; e < count; ++e) {
                const AdditiveExtension& ext = extensions[e];
                const size_t wordLen = dawg.wordForId(ext.word, wordBuf, sizeof(wordBuf));
                uint8_t offset = 0;
                if (!fluxcore::containsStem(wordBuf, static_cast<uint8_t>(wordLen), stemBuf,
                                            static_cast<uint8_t>(stemLen), &offset)) {
                    continue;
                }
                stem.extensions.emplace_back(ext.word, offset);
                std::string name;
                if (ext.back()) name = "-" + std::string(wordBuf + stemLen, ext.suffixLen);
                else if (ext.front()) name = std::string(wordBuf, ext.prefixLen) + "-";
                const auto it = affixIds.find(name);
                stem.affixIndex.push_back(it == affixIds.end() ? 0xFFFF : it->second);
            }
            if (stem.extensions.empty()) continue;
            ++perLen[stemLen];
            m1SlotOf[id] = static_cast<uint32_t>(m1Stems.size());
            m1Stems.push_back(std::move(stem));
        }
    }

    // --- M3 candidate stems: two samples, measured on the same boards -------
    // selfId is the stem's own word id when the stem is itself a word, so it
    // can be discounted from its own family; 0xFFFFFFFF for fragment stems.
    struct M3Stem { std::string text; std::vector<uint32_t> members; uint32_t selfId; };
    std::vector<M3Stem> m3Stems[kSampleCount];

    auto takeStem = [&](size_t family) -> M3Stem {
        M3Stem stem;
        stem.text = families.stem(family);
        uint32_t count = 0;
        const uint32_t* members = families.members(family, &count);
        stem.members.assign(members, members + count);
        stem.selfId = 0xFFFFFFFFu;
        uint32_t id = 0;
        if (dawg.findWordId(stem.text.c_str(), stem.text.size(), &id)) stem.selfId = id;
        return stem;
    };

    // Broad: stride the family index so the sample spreads across the
    // alphabet rather than piling into the A's. Unchanged from the first
    // report, so its numbers reproduce.
    {
        std::vector<uint32_t> perLen(kMaxStemLen + 1, 0);
        const uint32_t perLenCap = stemBudget / kMaxStemLen + 1;
        const size_t total = families.familyCount();
        const size_t stride = total > stemBudget * 8 ? total / (stemBudget * 8) : 1;
        for (size_t f = 0; f < total && m3Stems[kBroad].size() < stemBudget; f += stride) {
            const std::string text = families.stem(f);
            if (text.size() < 2 || text.size() > kMaxStemLen) continue;
            if (perLen[text.size()] >= perLenCap) continue;
            uint32_t count = 0;
            families.members(f, &count);
            if (count < 2) continue;
            ++perLen[text.size()];
            m3Stems[kBroad].push_back(takeStem(f));
        }
    }

    // Curated: rank by productivity, not by frequency. A stem's productivity
    // is the number of distinct valid completions it has, weighted by what
    // those completions score -- a stem whose family is six 3-letter words is
    // worth less to teach than one whose family is six 7-letter words, and
    // raw family size cannot tell them apart. Top `curatedPerLen` per length.
    {
        std::vector<uint8_t> lenOf(dawg.wordCount(), 0);
        char buf[64];
        for (uint32_t id = 0; id < dawg.wordCount(); ++id) {
            lenOf[id] = static_cast<uint8_t>(dawg.wordForId(id, buf, sizeof(buf)));
        }

        std::vector<std::pair<uint64_t, uint32_t>> ranked[kMaxStemLen + 1];      // (points, family)
        std::vector<std::pair<uint64_t, uint32_t>> rankedWord[kMaxStemLen + 1];  // stems that are words
        for (size_t f = 0; f < families.familyCount(); ++f) {
            const std::string text = families.stem(f);
            if (text.size() < 2 || text.size() > kMaxStemLen) continue;
            uint32_t count = 0;
            const uint32_t* members = families.members(f, &count);
            if (count < 2) continue;
            uint64_t points = 0;
            for (uint32_t m = 0; m < count; ++m) {
                points += loaded.config.scores.points(lenOf[members[m]]);
            }
            ranked[text.size()].emplace_back(points, static_cast<uint32_t>(f));
            uint32_t stemId = 0;
            if (dawg.findWordId(text.c_str(), text.size(), &stemId)) {
                rankedWord[text.size()].emplace_back(points, static_cast<uint32_t>(f));
            }
        }

        // Ties broken by family index so the sample is deterministic.
        auto byPoints = [](const auto& a, const auto& b) {
            if (a.first != b.first) return a.first > b.first;
            return a.second < b.second;
        };
        // Print the head of each length so the curation is auditable by eye
        // rather than taken on trust.
        auto head = [&](const char* label, uint8_t len,
                        const std::vector<std::pair<uint64_t, uint32_t>>& list, size_t take) {
            std::fprintf(stderr, "  %s %u-letter head:", label, len);
            for (size_t i = 0; i < std::min<size_t>(8, take); ++i) {
                std::fprintf(stderr, " %s(%llu)", families.stem(list[i].second).c_str(),
                             static_cast<unsigned long long>(list[i].first));
            }
            std::fprintf(stderr, "  [%zu ranked]\n", list.size());
        };

        for (uint8_t len = 2; len <= kMaxStemLen; ++len) {
            auto& list = ranked[len];
            const size_t take = std::min<size_t>(curatedPerLen, list.size());
            std::partial_sort(list.begin(), list.begin() + take, list.end(), byPoints);
            head("curated    ", len, list, take);
            const size_t tight = std::min<size_t>(curatedTight, take);
            for (size_t i = 0; i < take; ++i) {
                M3Stem stem = takeStem(list[i].second);
                if (i < tight) m3Stems[kCuratedTight].push_back(stem);
                m3Stems[kCurated].push_back(std::move(stem));
            }

            auto& wordList = rankedWord[len];
            const size_t takeWord = std::min<size_t>(curatedPerLen, wordList.size());
            std::partial_sort(wordList.begin(), wordList.begin() + takeWord, wordList.end(),
                              byPoints);
            head("curatedWord", len, wordList, takeWord);
            for (size_t i = 0; i < takeWord; ++i) {
                m3Stems[kCuratedWord].push_back(takeStem(wordList[i].second));
            }
        }
    }

    std::fprintf(stderr,
                 "  indices ready. M1 stems %zu; M3 stems %zu broad / %zu curated (top %u per "
                 "length) / %zu tight (top %u) / %zu word-only; mined affixes %zu; "
                 "%llu boards/cell\n",
                 m1Stems.size(), m3Stems[kBroad].size(), m3Stems[kCurated].size(), curatedPerLen,
                 m3Stems[kCuratedTight].size(), curatedTight, m3Stems[kCuratedWord].size(),
                 affixNames.size(), static_cast<unsigned long long>(boardsPerCell));

    SeedPool seeds;
    seeds.buildForRuleset(dawg, loaded.config);

    std::vector<std::pair<uint8_t, Tier>> cells;
    for (uint8_t side : {4, 5}) {
        for (Tier tier : {Tier::Casual, Tier::GoodCasual, Tier::Spam}) cells.emplace_back(side, tier);
    }

    std::vector<CellTallies> cellResults;
    for (const auto& [side, tier] : cells) {
        std::vector<CellTallies> perThread(threads);
        for (CellTallies& t : perThread) t.init(affixNames.size());

        std::vector<std::unique_ptr<Generator>> generators;
        std::vector<std::unique_ptr<Solver>> solvers;
        std::vector<SolveResult> scratch(threads);
        fluxcore::SolverOptions solverOptions = loaded.config.solver;
        for (unsigned t = 0; t < threads; ++t) {
            generators.push_back(std::make_unique<Generator>(dawg, loaded.config, seeds));
            solvers.push_back(std::make_unique<Solver>(dawg, loaded.config.scores, solverOptions));
        }

        // N quartile bounds for the Spam split, from the cell's own draw.
        const fluxcore::CandidateRange* range = nullptr;
        const fluxcore::GridConfig* grid = loaded.config.grid(side);
        if (grid) range = &grid->candidates[static_cast<uint8_t>(tier)];

        parallelFor(
            boardsPerCell, threads,
            [&](uint64_t index, unsigned t) {
                Board board;
                GenerationRecord record;
                if (!generators[t]->generate(side, tier, static_cast<uint32_t>(index), rootSeed,
                                             &board, &record)) {
                    return;
                }
                SolveResult& result = scratch[t];
                solvers[t]->solve(board, SolveMode::Full, &result);
                CellTallies& tally = perThread[t];
                const fluxcore::BoardGeometry& geom = solvers[t]->geometry(side);

                // word id -> slot in the result, for O(1) extension lookup.
                static thread_local std::unordered_map<uint32_t, uint32_t> slotOf;
                slotOf.clear();
                for (size_t i = 0; i < result.wordCount(); ++i) slotOf[result.wordIds[i]] = i;
                tally.foundWords += result.wordCount();

                // ---- M1 ------------------------------------------------------
                static thread_local std::vector<uint32_t> freeWords;
                freeWords.clear();
                for (size_t i = 0; i < result.wordCount(); ++i) {
                    const uint32_t slot = m1SlotOf[result.wordIds[i]];
                    if (slot == 0xFFFFFFFFu) continue;
                    const M1Stem& stem = m1Stems[slot];
                    const uint8_t stemLen = result.wordLens[i];
                    const uint32_t stemPaths = result.storedPathCounts[i];
                    if (stemPaths == 0) continue;
                    ++tally.m1StemInstances;

                    for (size_t e = 0; e < stem.extensions.size(); ++e) {
                        const auto [extId, offset] = stem.extensions[e];
                        const uint16_t affix = stem.affixIndex[e];
                        ReachTally* affixTally =
                            affix == 0xFFFF ? nullptr : &tally.byAffix[affix];

                        const auto found = slotOf.find(extId);
                        bool boardHit = false;
                        uint32_t pathHits = 0;

                        if (found != slotOf.end()) {
                            const size_t j = found->second;
                            const uint8_t extLen = result.wordLens[j];
                            // Does some extension path carry the stem's path
                            // at `offset`? That is the reachability condition.
                            for (uint32_t sp = 0; sp < stemPaths; ++sp) {
                                const uint8_t* stemCells =
                                    &result.pathCells[result.pathOffsets[i] + sp * stemLen];
                                bool hit = false;
                                for (uint32_t ep = 0; ep < result.storedPathCounts[j] && !hit; ++ep) {
                                    const uint8_t* extCells =
                                        &result.pathCells[result.pathOffsets[j] + ep * extLen];
                                    hit = std::equal(stemCells, stemCells + stemLen,
                                                     extCells + offset);
                                }
                                if (hit) { ++pathHits; boardHit = true; }
                            }
                        }

                        tally.overall.stemPaths += stemPaths;
                        tally.overall.pathHits += pathHits;
                        tally.overall.stemBoards += 1;
                        tally.overall.boardHits += boardHit ? 1 : 0;
                        tally.byStemLen[stemLen].stemPaths += stemPaths;
                        tally.byStemLen[stemLen].pathHits += pathHits;
                        tally.byStemLen[stemLen].stemBoards += 1;
                        tally.byStemLen[stemLen].boardHits += boardHit ? 1 : 0;
                        if (affixTally) {
                            affixTally->stemPaths += stemPaths;
                            affixTally->pathHits += pathHits;
                            affixTally->stemBoards += 1;
                            affixTally->boardHits += boardHit ? 1 : 0;
                        }
                        if (boardHit) {
                            ++tally.reachableExtensions;
                            freeWords.push_back(extId);
                        }
                    }
                }

                std::sort(freeWords.begin(), freeWords.end());
                freeWords.erase(std::unique(freeWords.begin(), freeWords.end()), freeWords.end());
                tally.distinctFreeWords += freeWords.size();
                ++tally.boardsWithStems;

                // ---- M2 ------------------------------------------------------
                ++tally.boardsForCellmates;
                for (size_t i = 0; i < result.wordCount(); ++i) {
                    const uint32_t id = result.wordIds[i];
                    const uint8_t len = result.wordLens[i];

                    uint32_t anagramCount = 0;
                    const uint32_t* members = anagrams.membersOf(id, &anagramCount);
                    for (uint32_t a = 0; a < anagramCount; ++a) {
                        if (members[a] == id) continue;
                        ++tally.anagramTrials[len];
                        if (slotOf.count(members[a])) ++tally.anagramHits[len];
                    }

                }

                // Drop-terminal words implied by the found set: every
                // contiguous sub-word of a found word is pathable by
                // construction (7.6), so this is a count, not a probability.
                // Sampled on a board stride because it is O(len^2) per word.
                if ((index & 15u) == 0) {
                    ++tally.dropTerminalBoards;
                    char wordBuf[64];
                    for (size_t i = 0; i < result.wordCount(); ++i) {
                        const size_t len = dawg.wordForId(result.wordIds[i], wordBuf, sizeof(wordBuf));
                        if (len < 4) continue;
                        ++tally.dropTerminalSourceWords;
                        for (size_t start = 0; start < len; ++start) {
                            for (size_t sub = 3; start + sub <= len; ++sub) {
                                if (sub == len) continue;  // the word itself
                                uint32_t subId = 0;
                                if (dawg.findWordId(wordBuf + start, sub, &subId)) {
                                    ++tally.dropTerminalImplied;
                                }
                            }
                        }
                    }
                }

                // ---- M3 ------------------------------------------------------
                uint8_t letterCounts[26] = {};
                for (uint8_t c = 0; c < board.cellCount(); ++c) ++letterCounts[board.letters[c]];

                int quartile = 0;
                if (range && range->maxN > range->minN) {
                    const uint32_t span = range->maxN - range->minN + 1;
                    const uint32_t offset = record.realizedN - range->minN;
                    quartile = static_cast<int>(std::min<uint32_t>(3, offset * 4 / span));
                }

                for (size_t sample = 0; sample < kSampleCount; ++sample) {
                    CellTallies::M3Tally& m3 = tally.m3[sample];
                    for (const M3Stem& stem : m3Stems[sample]) {
                        if (!stemHasPath(board, geom, stem.text.c_str(),
                                         static_cast<uint8_t>(stem.text.size()), letterCounts)) {
                            continue;
                        }
                        uint32_t findable = 0, findableOther = 0;
                        for (const uint32_t member : stem.members) {
                            if (!slotOf.count(member)) continue;
                            ++findable;
                            if (member != stem.selfId) ++findableOther;
                        }
                        const size_t len = stem.text.size();
                        ++m3.stemPresent[len];
                        m3.memberSum[len] += findable;
                        m3.memberSumOther[len] += findableOther;
                        ++m3.stemPresentQ[quartile][len];
                        m3.memberSumQ[quartile][len] += findable;
                        m3.memberSumOtherQ[quartile][len] += findableOther;
                    }
                }
            },
            [&](uint64_t done) {
                std::fprintf(stderr, "\r  %dx%d %-12s %llu / %llu", side, side, tierName(tier),
                             static_cast<unsigned long long>(done),
                             static_cast<unsigned long long>(boardsPerCell));
                std::fflush(stderr);
            });

        CellTallies merged;
        merged.init(affixNames.size());
        for (const CellTallies& t : perThread) merged.merge(t);
        cellResults.push_back(std::move(merged));
        std::fprintf(stderr, "\r  %dx%d %-12s done%20s\n", side, side, tierName(tier), "");
    }

    const double wallSeconds =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - runStart).count();

    // ---- outputs -----------------------------------------------------------
    std::ofstream reach(outDir + "/reachability.tsv");
    std::ofstream cellmates(outDir + "/cellmate_stats.tsv");
    std::ofstream familyStats(outDir + "/family_stats.tsv");
    if (!reach || !cellmates || !familyStats) {
        std::cerr << "\nerror: cannot write into " << outDir << "\n";
        return 1;
    }

    reach << "grid\ttier\tbreakdown\tkey\tstemPaths\tpathHits\tpPerPath\tstemBoards\tboardHits\tpPerBoard\n";
    cellmates << "grid\ttier\trelation\tlen\ttrials\thits\tp\n";
    familyStats << "grid\ttier\tsample\tstemLen\tnQuartile\tstemPresent\tmemberSum\tenumerability"
                   "\tmemberSumOther\tenumerabilityOther\n";

    auto emitReach = [&](std::ofstream& out, const std::string& lead, const char* kind,
                         const std::string& key, const ReachTally& tally) {
        if (tally.stemPaths == 0) return;
        out << lead << '\t' << kind << '\t' << key << '\t' << tally.stemPaths << '\t'
            << tally.pathHits << '\t'
            << static_cast<double>(tally.pathHits) / static_cast<double>(tally.stemPaths) << '\t'
            << tally.stemBoards << '\t' << tally.boardHits << '\t'
            << static_cast<double>(tally.boardHits) / static_cast<double>(tally.stemBoards) << '\n';
    };

    for (size_t c = 0; c < cellResults.size(); ++c) {
        const CellTallies& tally = cellResults[c];
        const std::string grid = std::to_string(cells[c].first) + "x" + std::to_string(cells[c].first);
        const std::string lead = grid + "\t" + tierName(cells[c].second);

        emitReach(reach, lead, "overall", "all", tally.overall);
        for (size_t len = 0; len < tally.byStemLen.size(); ++len) {
            emitReach(reach, lead, "stemLen", std::to_string(len), tally.byStemLen[len]);
        }
        for (size_t a = 0; a < tally.byAffix.size(); ++a) {
            emitReach(reach, lead, "affix", affixNames[a], tally.byAffix[a]);
        }

        for (size_t len = 0; len < tally.anagramTrials.size(); ++len) {
            if (tally.anagramTrials[len] > 0) {
                cellmates << lead << "\tanagram\t" << len << '\t' << tally.anagramTrials[len] << '\t'
                          << tally.anagramHits[len] << '\t'
                          << static_cast<double>(tally.anagramHits[len]) /
                                 static_cast<double>(tally.anagramTrials[len])
                          << '\n';
            }
        }

        for (size_t sample = 0; sample < kSampleCount; ++sample) {
            const CellTallies::M3Tally& m3 = tally.m3[sample];
            const std::string m3Lead = lead + "\t" + kSampleNames[sample];
            for (size_t len = 0; len < m3.stemPresent.size(); ++len) {
                if (m3.stemPresent[len] == 0) continue;
                familyStats << m3Lead << '\t' << len << "\tall\t" << m3.stemPresent[len] << '\t'
                            << m3.memberSum[len] << '\t'
                            << static_cast<double>(m3.memberSum[len]) /
                                   static_cast<double>(m3.stemPresent[len])
                            << '\t' << m3.memberSumOther[len] << '\t'
                            << static_cast<double>(m3.memberSumOther[len]) /
                                   static_cast<double>(m3.stemPresent[len])
                            << '\n';
                for (int q = 0; q < 4; ++q) {
                    if (m3.stemPresentQ[q][len] == 0) continue;
                    familyStats << m3Lead << '\t' << len << "\tQ" << (q + 1) << '\t'
                                << m3.stemPresentQ[q][len] << '\t' << m3.memberSumQ[q][len] << '\t'
                                << static_cast<double>(m3.memberSumQ[q][len]) /
                                       static_cast<double>(m3.stemPresentQ[q][len])
                                << '\t' << m3.memberSumOtherQ[q][len] << '\t'
                                << static_cast<double>(m3.memberSumOtherQ[q][len]) /
                                       static_cast<double>(m3.stemPresentQ[q][len])
                                << '\n';
                }
            }
        }
    }

    // ---- headline numbers to stderr ---------------------------------------
    std::fprintf(stderr, "\n==== M1 reachability ====\n");
    std::fprintf(stderr, "  %-16s %11s %11s %13s %13s\n", "cell", "ext/stem",
                 "freeWords/bd", "foundWords/bd", "freeFraction");
    double weightedExtra = 0, weightedBoards = 0;
    for (size_t c = 0; c < cellResults.size(); ++c) {
        const CellTallies& t = cellResults[c];
        if (t.overall.stemPaths == 0) continue;
        const double perPath =
            static_cast<double>(t.overall.pathHits) / static_cast<double>(t.overall.stemPaths);
        const double perBoard =
            static_cast<double>(t.overall.boardHits) / static_cast<double>(t.overall.stemBoards);
        // Extra words per game: reachable additive extensions per found word,
        // times ~100 swipes (3.5 / the build prompt's assumption).
        const double perFound = t.m1StemInstances
                                    ? static_cast<double>(t.reachableExtensions) /
                                          static_cast<double>(t.m1StemInstances)
                                    : 0.0;
        char cell[32];
        std::snprintf(cell, sizeof(cell), "%dx%d %s", cells[c].first, cells[c].first,
                      tierName(cells[c].second));
        const double freePerBoard = t.boardsWithStems
                                        ? static_cast<double>(t.distinctFreeWords) /
                                              static_cast<double>(t.boardsWithStems)
                                        : 0.0;
        const double foundPerBoard = t.boardsWithStems
                                         ? static_cast<double>(t.foundWords) /
                                               static_cast<double>(t.boardsWithStems)
                                         : 0.0;
        (void)perPath;
        (void)perBoard;
        std::fprintf(stderr, "  %-16s %11.2f %11.1f %13.1f %12.1f%%\n", cell, perFound,
                     freePerBoard, foundPerBoard,
                     foundPerBoard ? 100.0 * freePerBoard / foundPerBoard : 0.0);
        weightedExtra += perFound;
        weightedBoards += 1;
    }
    std::fprintf(stderr,
                 "  mean reachable additive extensions per found stem: %.2f\n"
                 "  (spec 15 gate: does this imply ~2 extra words a game, or 10+?)\n",
                 weightedBoards ? weightedExtra / weightedBoards : 0.0);

    // M3, broad against curated, same boards. 7.5.1 predicts the 4-to-6 band
    // survives; the broad sample said only 3-letter stems reach it. If that
    // was a sampling artefact, curation moves these columns apart.
    std::fprintf(stderr,
                 "\n==== M3 enumerability: E[OTHER members findable | stem present] ====\n"
                 "  (excludes the stem itself, which a word stem always finds and a\n"
                 "   fragment stem never can; family_stats.tsv carries both columns)\n");
    std::fprintf(stderr, "  %-16s %8s", "cell", "stemLen");
    for (size_t s = 0; s < kSampleCount; ++s) std::fprintf(stderr, " %13s", kSampleNames[s]);
    std::fprintf(stderr, " %14s\n", "tight/broad");
    for (size_t c = 0; c < cellResults.size(); ++c) {
        char cell[32];
        std::snprintf(cell, sizeof(cell), "%dx%d %s", cells[c].first, cells[c].first,
                      tierName(cells[c].second));
        for (size_t len = 2; len <= kMaxStemLen; ++len) {
            double value[kSampleCount] = {};
            bool any = false;
            for (size_t s = 0; s < kSampleCount; ++s) {
                const CellTallies::M3Tally& m3 = cellResults[c].m3[s];
                if (m3.stemPresent[len] == 0) continue;
                // Ex-self, so a word stem is not credited with finding itself.
                value[s] = static_cast<double>(m3.memberSumOther[len]) /
                           static_cast<double>(m3.stemPresent[len]);
                any = true;
            }
            if (!any) continue;
            std::fprintf(stderr, "  %-16s %8zu", len == 2 ? cell : "", len);
            for (size_t s = 0; s < kSampleCount; ++s) std::fprintf(stderr, " %13.2f", value[s]);
            std::fprintf(stderr, " %13.2fx\n",
                         value[kBroad] > 0 ? value[kCuratedTight] / value[kBroad] : 0.0);
        }
    }
    std::fprintf(stderr,
                 "  (7.5.1 target band is 2 to 6 findable members; the question is whether\n"
                 "   4- and 5-letter stems reach it under curation or stay near 1)\n");

    Manifest manifest;
    manifest.tool = "measure";
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
    for (size_t c = 0; c < cells.size(); ++c) {
        manifest.boardsPerCell.emplace_back(
            std::to_string(cells[c].first) + "x" + std::to_string(cells[c].first) + ":" +
                tierName(cells[c].second),
            boardsPerCell);
    }
    manifest.extra.emplace_back("m1Stems", std::to_string(m1Stems.size()));
    manifest.extra.emplace_back("m3StemsBroad", std::to_string(m3Stems[kBroad].size()));
    manifest.extra.emplace_back("m3StemsCurated", std::to_string(m3Stems[kCurated].size()));
    manifest.extra.emplace_back("m3StemsCuratedTight", std::to_string(m3Stems[kCuratedTight].size()));
    manifest.extra.emplace_back("m3StemsCuratedWord", std::to_string(m3Stems[kCuratedWord].size()));
    manifest.extra.emplace_back("curatedPerLen", std::to_string(curatedPerLen));
    manifest.extra.emplace_back("curatedTight", std::to_string(curatedTight));
    manifest.extra.emplace_back("curationRule",
                                "family points = sum of scores.points(len) over members; "
                                "top curatedPerLen per stem length");
    manifest.extra.emplace_back("minedAffixes", std::to_string(affixNames.size()));
    if (!writeManifest(manifest, outDir + "/manifest.json", &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }

    std::fprintf(stderr, "\ndone in %.1fs -> %s\n", wallSeconds, outDir.c_str());
    return 0;
}
