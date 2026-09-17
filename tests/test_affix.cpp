#include "affix.h"

#include "dawg_builder.h"
#include "lexicon.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <fstream>
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

using fluxcore::AffixClass;
using fluxcore::Dawg;
using fluxcore::LiveAffix;
using fluxcore::MutationCandidate;
using fluxcore::MutationRule;
using namespace fluxcore::build;

namespace {

bool contains(const std::string& word, const std::string& stem) {
    uint8_t offset = 0;
    return fluxcore::containsStem(word.c_str(), static_cast<uint8_t>(word.size()), stem.c_str(),
                                  static_cast<uint8_t>(stem.size()), &offset);
}

AffixClass classify(const std::string& form, const std::string& stem, bool isWord) {
    return fluxcore::classifyForm(form.c_str(), static_cast<uint8_t>(form.size()), stem.c_str(),
                                  static_cast<uint8_t>(stem.size()), isWord);
}

// Spec 7.3: classification is substring containment, not morphology. These
// are the spec's own worked examples.
void testContainmentClassification() {
    CHECK(contains("PRATERS", "PRATE"));
    CHECK(contains("PRATER", "PRATE"));
    CHECK(!contains("PRATING", "PRATE"));  // the E is consumed
    CHECK(contains("EPATERS", "PATERS"));  // front extension
    CHECK(contains("CANTERED", "ANTE"));   // interior occurrence still contains

    // The case that decides the 3.5 / 7.3 contradiction: consonant doubling
    // keeps the stem contiguous, so it IS additive.
    CHECK(contains("BATTING", "BAT"));
    CHECK(classify("BATTING", "BAT", true) == AffixClass::Additive);

    // Y -> I genuinely destroys the stem, so it is not.
    CHECK(!contains("SANTIER", "SANTY"));
    CHECK(classify("SANTIER", "SANTY", true) == AffixClass::Mutating);

    CHECK(classify("PRATER", "PRATE", true) == AffixClass::Additive);
    CHECK(classify("PRATING", "PRATE", true) == AffixClass::Mutating);
    CHECK(classify("PRATIER", "PRATE", false) == AffixClass::Dead);

    // Offset is where the stem starts, i.e. how many cells precede it.
    uint8_t offset = 99;
    CHECK(fluxcore::containsStem("EPATERS", 7, "PATERS", 6, &offset));
    CHECK(offset == 1);
    CHECK(fluxcore::containsStem("PRATERS", 7, "PRATE", 5, &offset));
    CHECK(offset == 0);

    // Degenerate inputs
    CHECK(!contains("CAT", "CATS"));  // stem longer than word
    CHECK(contains("CAT", "CAT"));    // identity
}

// Mutation rules survive only as candidate generators for the misswipe
// track. They decide neither validity nor class.
void testMutationsAreCandidatesOnly() {
    MutationCandidate out[4];

    size_t n = fluxcore::generateMutations("PRATE", 5, "ING", 3, out, 4);
    CHECK(n == 1);
    CHECK(std::string(out[0].form, out[0].len) == "PRATING");
    CHECK(out[0].rule == MutationRule::DropFinalE);
    // ... and containment, not the rule, is what says it is not free points.
    CHECK(classify("PRATING", "PRATE", true) == AffixClass::Mutating);

    n = fluxcore::generateMutations("SANTY", 5, "ER", 2, out, 4);
    CHECK(n == 1);
    CHECK(std::string(out[0].form, out[0].len) == "SANTIER");
    CHECK(out[0].rule == MutationRule::YToI);

    n = fluxcore::generateMutations("BAT", 3, "ING", 3, out, 4);
    CHECK(n == 1);
    CHECK(std::string(out[0].form, out[0].len) == "BATTING");
    CHECK(out[0].rule == MutationRule::DoubleFinalConsonant);
    // The doubled form still contains BAT, so it is additive despite being
    // produced by a mutation rule. This is the whole point of the split.
    CHECK(classify("BATTING", "BAT", true) == AffixClass::Additive);

    // Y after a vowel must not become I, or PLAYED is unreachable.
    n = fluxcore::generateMutations("PLAY", 4, "ED", 2, out, 4);
    CHECK(n == 0);

    // W/X never double, or BOXING is unreachable.
    n = fluxcore::generateMutations("BOX", 3, "ING", 3, out, 4);
    CHECK(n == 0);
}

// Live affixes come from the DAWG subtree, never a list.
void testLiveAffixesFromDawg() {
    std::vector<std::string> words = {"PRATE",  "PRATED", "PRATER", "PRATERS", "PRATES",
                                      "PRATING", "CAT",   "CATS",   "CATTY"};
    std::sort(words.begin(), words.end());
    const std::vector<uint8_t> bytes = serializeDawg(buildDawg(words));
    Dawg dawg;
    CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));

    LiveAffix found[32];
    const size_t n = fluxcore::enumerateLiveAffixes(dawg, "PRATE", 5, 6, found, 32);

    std::set<std::string> affixes;
    for (size_t i = 0; i < n; ++i) affixes.insert(std::string(found[i].letters, found[i].len));

    // Exactly the dictionary's continuations of PRATE: D, R, RS, S.
    // PRATING is NOT here -- it is not a continuation of PRATE, which is
    // precisely why a hand-written list gets this wrong.
    const std::set<std::string> expected = {"D", "R", "RS", "S"};
    CHECK(affixes == expected);

    // Every reported continuation completes a real word, and the reported
    // word ID round-trips.
    char buf[64];
    for (size_t i = 0; i < n; ++i) {
        const std::string whole = "PRATE" + std::string(found[i].letters, found[i].len);
        const size_t len = dawg.wordForId(found[i].wordId, buf, sizeof(buf));
        CHECK(std::string(buf, len) == whole);
        CHECK(found[i].wordLen == whole.size());
    }

    // A stem that is not a prefix of anything yields nothing.
    CHECK(fluxcore::enumerateLiveAffixes(dawg, "ZZZ", 3, 6, found, 32) == 0);
    // A stem that is a prefix but has no continuations yields nothing.
    CHECK(fluxcore::enumerateLiveAffixes(dawg, "CATTY", 5, 6, found, 32) == 0);
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

// Against the real dictionary: the mined affix set must be derived, and the
// live-affix walk must agree with the containment-based extension index.
void testAgainstRealDictionary(const std::string& path) {
    const std::vector<std::string> words = loadWordList(path);
    if (words.empty()) {
        std::fprintf(stderr, "skip: could not load %s\n", path.c_str());
        return;
    }
    const std::vector<uint8_t> bytes = serializeDawg(buildDawg(words));
    Dawg dawg;
    CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));

    // Spec 7.3's own worked example is dead against real CSW21.
    uint32_t id = 0;
    CHECK(!dawg.findWordId("SANTY", 5, &id));
    CHECK(!dawg.findWordId("SANTIER", 7, &id));

    // Live affixes of PRATE, straight from the subtree.
    LiveAffix found[512];
    const size_t n = fluxcore::enumerateLiveAffixes(dawg, "PRATE", 5, 8, found, 512);
    CHECK(n > 0);
    bool sawS = false, sawR = false;
    for (size_t i = 0; i < n; ++i) {
        const std::string affix(found[i].letters, found[i].len);
        if (affix == "S") sawS = true;
        if (affix == "R") sawR = true;
        // Everything the walk reports is a word containing the stem.
        const std::string whole = "PRATE" + affix;
        uint32_t wholeId = 0;
        CHECK(dawg.findWordId(whole.c_str(), whole.size(), &wholeId));
        CHECK(wholeId == found[i].wordId);
        CHECK(contains(whole, "PRATE"));
    }
    CHECK(sawS);
    CHECK(sawR);

    std::fprintf(stderr, "real dictionary: PRATE has %zu live suffixes up to 8 letters\n", n);
}

}  // namespace

int main(int argc, char** argv) {
    testContainmentClassification();
    testMutationsAreCandidatesOnly();
    testLiveAffixesFromDawg();

    if (argc > 1) {
        testAgainstRealDictionary(argv[1]);
    } else {
        std::fprintf(stderr, "note: pass a word-list path as argv[1] for the dictionary tests\n");
    }

    std::fprintf(stderr, "%d/%d checks passed\n", g_checks - g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
