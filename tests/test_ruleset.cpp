#include "config_json.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

// The shipped ruleset files, checked against the values the spec confirms
// (spec 2.3, from flux-ios), and the versioned schema that keeps v1 meaning
// what it meant when its runs were made.

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

using fluxcore::CandidateDraw;
using fluxcore::FillOrder;
using fluxcore::RulesetConfig;
using fluxcore::SeedPlacement;
using fluxcore::SeedScope;
using fluxcore::config::LoadResult;

namespace {

std::string readText(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

bool parses(const std::string& text, std::string* error = nullptr) {
    LoadResult result;
    std::string scratch;
    return fluxcore::config::parseRulesetConfig(text.data(), text.size(), "test", &result,
                                                error ? error : &scratch);
}

std::string replaceOnce(std::string text, const std::string& from, const std::string& to) {
    const size_t at = text.find(from);
    if (at == std::string::npos) return std::string();
    return text.replace(at, from.size(), to);
}

// Spec 2.3 item: the client's letterFrequencies table (flux-ios@fa8fb2d),
// written out here literally rather than read from the file under test.
void testV3LetterTable(const RulesetConfig& config) {
    const struct { char letter; uint32_t weight; } table[26] = {
        {'E', 1202}, {'T', 910}, {'A', 812}, {'O', 768}, {'I', 731}, {'N', 695}, {'S', 628},
        {'R', 602},  {'H', 592}, {'D', 432}, {'L', 398}, {'U', 288}, {'C', 271}, {'M', 261},
        {'F', 230},  {'Y', 211}, {'W', 209}, {'G', 203}, {'P', 182}, {'B', 149}, {'V', 111},
        {'K', 69},   {'X', 17},  {'Q', 11},  {'J', 10},  {'Z', 7}};
    for (const auto& entry : table) {
        CHECK(config.letterWeights[entry.letter - 'A'] == entry.weight);
    }
    CHECK(config.letterWeightTotal() == 9999);
}

void testShippedFiles(const std::string& root) {
    LoadResult v3;
    std::string error;
    CHECK(fluxcore::config::loadRulesetConfig(root + "/config/ruleset_v3.json", &v3, &error));
    if (!error.empty()) std::fprintf(stderr, "  %s\n", error.c_str());
    const RulesetConfig& c3 = v3.config;
    CHECK(c3.version == 3);
    testV3LetterTable(c3);
    CHECK(c3.maxPerLetter == 2);
    CHECK(c3.fillOrder == FillOrder::Random);
    CHECK(c3.seedScope == SeedScope::PerBoard);
    CHECK(c3.seedPlacement == SeedPlacement::RandomWalk);
    CHECK(c3.candidateDraw == CandidateDraw::UniformQuality);
    CHECK(c3.seedProbabilityPerMille == 500);
    CHECK(c3.dictionaryPinned);
    CHECK(c3.dictionaryHash == 0xfa4bad1daff9c8d6ull);
    CHECK(c3.dictionaryWords == 223493);

    // v1 must keep its old semantics, and its bytes, so every v1 artifact's
    // recorded config hash still names this file.
    LoadResult v1;
    CHECK(fluxcore::config::loadRulesetConfig(root + "/config/ruleset_v1.json", &v1, &error));
    const RulesetConfig& c1 = v1.config;
    CHECK(c1.version == 1);
    CHECK(c1.configHash == 0x22448ec0ab243759ull);
    CHECK(c1.maxPerLetter == 0);
    CHECK(c1.fillOrder == FillOrder::RowMajor);
    CHECK(c1.seedScope == SeedScope::PerCandidate);
    CHECK(c1.seedPlacement == SeedPlacement::BacktrackingDfs);
    CHECK(c1.candidateDraw == CandidateDraw::UniformN);
    CHECK(!c1.dictionaryPinned);
    CHECK(c1.letterWeights['E' - 'A'] == 11280);  // the CSW21-word-frequency placeholder
}

// The generation and dictionary blocks are schema by version: required from
// v3, forbidden before it, and every field inside them is required.
void testSchemaGate(const std::string& root) {
    const std::string v1 = readText(root + "/config/ruleset_v1.json");
    const std::string v3 = readText(root + "/config/ruleset_v3.json");
    CHECK(parses(v1));
    CHECK(parses(v3));

    std::string error;
    // v1 with a generation block: rejected, bump the version instead.
    const std::string v1WithBlock = replaceOnce(
        v1, "\"version\": 1,",
        "\"version\": 1, \"generation\": {\"maxPerLetter\": 2, \"fillOrder\": \"random\", "
        "\"seedScope\": \"perBoard\", \"seedPlacement\": \"randomWalk\", \"candidateDraw\": "
        "\"uniformQuality\"},");
    CHECK(!v1WithBlock.empty());
    CHECK(!parses(v1WithBlock, &error));
    CHECK(error.find("not allowed before ruleset version 3") != std::string::npos);

    // v3 without its blocks: rejected rather than silently read as v1.
    const std::string noGeneration = replaceOnce(v3, "\"generation\": {", "\"_generationRemoved\": {");
    CHECK(!parses(noGeneration, &error));
    CHECK(error.find("generation") != std::string::npos);
    const std::string noDictionary = replaceOnce(v3, "\"dictionary\": {", "\"_dictionaryRemoved\": {");
    CHECK(!parses(noDictionary, &error));

    // A missing field inside the block, or a misspelled enum, is an error.
    CHECK(!parses(replaceOnce(v3, "\"maxPerLetter\": 2,", "")));
    CHECK(!parses(replaceOnce(v3, "\"seedScope\": \"perBoard\"", "\"seedScope\": \"perboard\"")));
    CHECK(!parses(replaceOnce(v3, "\"sourceHash\": \"0xfa4bad1daff9c8d6\"",
                              "\"sourceHash\": \"fa4bad1daff9c8d6\"")));

    // One seed word per board has no meaning for LetterCounter's extra seeds.
    const std::string extra = replaceOnce(
        replaceOnce(v3, "\"extraSeedCount\": 0", "\"extraSeedCount\": 1"),
        "\"allowSeedOverlap\": false", "\"allowSeedOverlap\": true");
    CHECK(!parses(extra, &error));
    CHECK(error.find("perBoard") != std::string::npos);

    // A cap of 1 still fits a 5x5 (26 letters >= 25 cells), so it loads.
    CHECK(parses(replaceOnce(v3, "\"maxPerLetter\": 2,", "\"maxPerLetter\": 1,")));
}

void testDictionaryCheck(const std::string& root) {
    LoadResult v3, v1;
    std::string error;
    CHECK(fluxcore::config::loadRulesetConfig(root + "/config/ruleset_v3.json", &v3, &error));
    CHECK(fluxcore::config::loadRulesetConfig(root + "/config/ruleset_v1.json", &v1, &error));

    // The pinned DAWG passes.
    CHECK(fluxcore::config::checkDictionary(v3.config, 0xfa4bad1daff9c8d6ull, 223493, &error));
    // Full CSW21 (the Phase 1 dictionary) is refused, loudly.
    error.clear();
    CHECK(!fluxcore::config::checkDictionary(v3.config, 0x1c8a4e773eafd14aull, 279496, &error));
    CHECK(error.find("dictionary mismatch") != std::string::npos);
    // Same hash, wrong word count, is refused too: the pin is both.
    CHECK(!fluxcore::config::checkDictionary(v3.config, 0xfa4bad1daff9c8d6ull, 223492, &error));
    // Unpinned v1 accepts anything; the tools print a warning instead.
    CHECK(fluxcore::config::checkDictionary(v1.config, 0x1c8a4e773eafd14aull, 279496, &error));
}

}  // namespace

int main() {
    const std::string root = FLUX_SOURCE_DIR;
    testShippedFiles(root);
    testSchemaGate(root);
    testDictionaryCheck(root);
    std::fprintf(stderr, "%d/%d checks passed\n", g_checks - g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
