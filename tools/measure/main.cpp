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

    // M3
    std::vector<uint64_t> stemPresent, memberSum;  // by stem length
    std::vector<uint64_t> stemPresentQ[4], memberSumQ[4];  // split at N quartiles

    void init(size_t affixes) {
        byAffix.assign(affixes, {});
        byStemLen.assign(fluxcore::kMaxCells + 1, {});
        anagramTrials.assign(fluxcore::kMaxCells + 1, 0);
        anagramHits.assign(fluxcore::kMaxCells + 1, 0);
        interiorTrials.assign(fluxcore::kMaxCells + 1, 0);
        interiorHits.assign(fluxcore::kMaxCells + 1, 0);
        stemPresent.assign(kMaxStemLen + 1, 0);
        memberSum.assign(kMaxStemLen + 1, 0);
        for (int q = 0; q < 4; ++q) {
            stemPresentQ[q].assign(kMaxStemLen + 1, 0);
            memberSumQ[q].assign(kMaxStemLen + 1, 0);
        }
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
        for (size_t i = 0; i < stemPresent.size(); ++i) {
            stemPresent[i] += other.stemPresent[i];
            memberSum[i] += other.memberSum[i];
            for (int q = 0; q < 4; ++q) {
                stemPresentQ[q][i] += other.stemPresentQ[q][i];
                memberSumQ[q][i] += other.memberSumQ[q][i];
            }
        }
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
        else if (arg == "--threads") threads = static_cast<unsigned>(std::stoul(next("--threads")));
        else {
            std::cerr << "usage: measure --config <f> --dawg <f> --out <dir> "
                         "[--boards-per-cell N] [--stems N] [--threads T] [--seed S]\n";
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

    // --- M3 candidate stems: bounded, stratified by stem length -------------
    struct M3Stem { std::string text; std::vector<uint32_t> members; };
    std::vector<M3Stem> m3Stems;
    {
        std::vector<uint32_t> perLen(kMaxStemLen + 1, 0);
        const uint32_t perLenCap = stemBudget / kMaxStemLen + 1;
        // Walk families in stride so the sample is spread across the
        // alphabet rather than concentrated in the A's.
        const size_t total = families.familyCount();
        const size_t stride = total > stemBudget * 8 ? total / (stemBudget * 8) : 1;
        for (size_t f = 0; f < total && m3Stems.size() < stemBudget; f += stride) {
            const std::string text = families.stem(f);
            if (text.size() < 2 || text.size() > kMaxStemLen) continue;
            if (perLen[text.size()] >= perLenCap) continue;
            uint32_t count = 0;
            const uint32_t* members = families.members(f, &count);
            if (count < 2) continue;
            M3Stem stem;
            stem.text = text;
            stem.members.assign(members, members + count);
            ++perLen[text.size()];
            m3Stems.push_back(std::move(stem));
        }
    }

    std::fprintf(stderr,
                 "  indices ready. M1 stems %zu, M3 stems %zu, mined affixes %zu, %llu boards/cell\n",
                 m1Stems.size(), m3Stems.size(), affixNames.size(),
                 static_cast<unsigned long long>(boardsPerCell));

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

                for (const M3Stem& stem : m3Stems) {
                    if (!stemHasPath(board, geom, stem.text.c_str(),
                                     static_cast<uint8_t>(stem.text.size()), letterCounts)) {
                        continue;
                    }
                    uint32_t findable = 0;
                    for (const uint32_t member : stem.members) {
                        if (slotOf.count(member)) ++findable;
                    }
                    const size_t len = stem.text.size();
                    ++tally.stemPresent[len];
                    tally.memberSum[len] += findable;
                    ++tally.stemPresentQ[quartile][len];
                    tally.memberSumQ[quartile][len] += findable;
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
    familyStats << "grid\ttier\tstemLen\tnQuartile\tstemPresent\tmemberSum\tenumerability\n";

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

        for (size_t len = 0; len < tally.stemPresent.size(); ++len) {
            if (tally.stemPresent[len] == 0) continue;
            familyStats << lead << '\t' << len << "\tall\t" << tally.stemPresent[len] << '\t'
                        << tally.memberSum[len] << '\t'
                        << static_cast<double>(tally.memberSum[len]) /
                               static_cast<double>(tally.stemPresent[len])
                        << '\n';
            for (int q = 0; q < 4; ++q) {
                if (tally.stemPresentQ[q][len] == 0) continue;
                familyStats << lead << '\t' << len << "\tQ" << (q + 1) << '\t'
                            << tally.stemPresentQ[q][len] << '\t' << tally.memberSumQ[q][len] << '\t'
                            << static_cast<double>(tally.memberSumQ[q][len]) /
                                   static_cast<double>(tally.stemPresentQ[q][len])
                            << '\n';
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
    manifest.startedUtc = utcTimestamp();
    for (size_t c = 0; c < cells.size(); ++c) {
        manifest.boardsPerCell.emplace_back(
            std::to_string(cells[c].first) + "x" + std::to_string(cells[c].first) + ":" +
                tierName(cells[c].second),
            boardsPerCell);
    }
    manifest.extra.emplace_back("m1Stems", std::to_string(m1Stems.size()));
    manifest.extra.emplace_back("m3Stems", std::to_string(m3Stems.size()));
    manifest.extra.emplace_back("minedAffixes", std::to_string(affixNames.size()));
    if (!writeManifest(manifest, outDir + "/manifest.json", &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }

    std::fprintf(stderr, "\ndone in %.1fs -> %s\n", wallSeconds, outDir.c_str());
    return 0;
}
