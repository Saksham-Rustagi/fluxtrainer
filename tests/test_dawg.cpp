#include "dawg.h"
#include "dawg_builder.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <random>
#include <set>
#include <string>
#include <unordered_set>
#include <vector>

namespace {

int g_checks = 0;
int g_failures = 0;

}  // namespace

#define CHECK(cond)                                                                    \
    do {                                                                               \
        ++g_checks;                                                                    \
        if (!(cond)) {                                                                 \
            ++g_failures;                                                              \
            std::fprintf(stderr, "CHECK FAILED at %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        }                                                                              \
    } while (0)

using fluxcore::Dawg;
using namespace fluxcore::build;

namespace {

fluxcore::Dawg buildAndLoad(const std::vector<std::string>& sortedWords, std::vector<uint8_t>& storage) {
    BuiltDawg built = buildDawg(sortedWords);
    storage = serializeDawg(built);
    Dawg dawg;
    bool ok = dawg.loadFromMemory(storage.data(), storage.size());
    CHECK(ok);
    return dawg;
}

void testSmallRoundTrip() {
    std::vector<std::string> words = {"CAT", "CATS", "CATER", "CATERS", "DOG", "DOGS", "AA"};
    std::sort(words.begin(), words.end());

    std::vector<uint8_t> storage;
    Dawg dawg = buildAndLoad(words, storage);
    CHECK(dawg.wordCount() == words.size());

    std::set<uint32_t> seenIds;
    for (const std::string& w : words) {
        uint32_t id = 0;
        bool found = dawg.findWordId(w.c_str(), w.size(), &id);
        CHECK(found);
        CHECK(id < dawg.wordCount());
        CHECK(seenIds.insert(id).second);
    }
    CHECK(seenIds.size() == words.size());
    CHECK(*seenIds.begin() == 0);
    CHECK(*seenIds.rbegin() == words.size() - 1);

    for (const std::string& bad : {std::string("CA"), std::string("CATE"), std::string("DOGGY"),
                                    std::string("XYZ"), std::string("")}) {
        uint32_t id = 0;
        if (bad.empty()) {
            CHECK(!dawg.findWordId(bad.c_str(), bad.size(), &id));
            continue;
        }
        CHECK(!dawg.findWordId(bad.c_str(), bad.size(), &id));
    }

    char buf[64];
    for (const std::string& w : words) {
        uint32_t id = 0;
        CHECK(dawg.findWordId(w.c_str(), w.size(), &id));
        size_t len = dawg.wordForId(id, buf, sizeof(buf));
        CHECK(len == w.size());
        CHECK(std::string(buf, len) == w);
    }

    CHECK(dawg.wordForId(dawg.wordCount(), buf, sizeof(buf)) == 0);  // out of range
}

void testRebuildIsByteIdentical() {
    std::vector<std::string> words = {"APPLE", "APP", "APPS", "APE", "APES", "BAT", "BATS", "BATTER"};
    std::sort(words.begin(), words.end());

    std::vector<uint8_t> a, b;
    { Dawg d = buildAndLoad(words, a); (void)d; }
    { Dawg d = buildAndLoad(words, b); (void)d; }

    CHECK(a.size() == b.size());
    CHECK(a == b);
}

void testMinimizationSharesStates() {
    // FIRE/HIRE and FIRES/HIRES share the identical suffix automaton for
    // "IRE"/"IRES", so the minimized DAWG should have far fewer states
    // than a trie over the same words would.
    std::vector<std::string> words = {"FIRE", "FIRES", "HIRE", "HIRES", "MIRE", "MIRES"};
    std::sort(words.begin(), words.end());

    BuiltDawg built = buildDawg(words);
    // A trie would need 1(root) + 3*4 = 13 nodes minimum for these 6 words
    // (each of FIRE/HIRE/MIRE contributes 4 unshared nodes, plus S).
    // The minimal DAWG collapses the identical "IRE"/"IRES" suffixes.
    CHECK(built.stateEdgeStart.size() < 13);
}

std::vector<std::string> loadUppercaseSorted(const std::string& path, size_t limit = 0) {
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
        bool valid = std::all_of(line.begin(), line.end(), [](char c) { return c >= 'A' && c <= 'Z'; });
        if (!valid) continue;
        words.push_back(std::move(line));
        if (limit && words.size() >= limit) break;
    }
    std::sort(words.begin(), words.end());
    words.erase(std::unique(words.begin(), words.end()), words.end());
    return words;
}

void testFullDictionary(const std::string& path) {
    std::vector<std::string> words = loadUppercaseSorted(path);
    if (words.empty()) {
        std::fprintf(stderr, "skip: could not load word list from %s\n", path.c_str());
        return;
    }
    std::fprintf(stderr, "full-dictionary test: %zu words from %s\n", words.size(), path.c_str());

    auto t0 = std::chrono::steady_clock::now();
    BuiltDawg built = buildDawg(words);
    auto t1 = std::chrono::steady_clock::now();
    std::vector<uint8_t> bytes = serializeDawg(built);
    auto t2 = std::chrono::steady_clock::now();

    double buildMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double serializeMs = std::chrono::duration<double, std::milli>(t2 - t1).count();
    double mb = static_cast<double>(bytes.size()) / (1024.0 * 1024.0);
    std::fprintf(stderr, "  states=%zu edges=%zu bytes=%zu (%.2f MB) build=%.1fms serialize=%.1fms\n",
                 built.stateEdgeStart.size(), built.edges.size(), bytes.size(), mb, buildMs, serializeMs);

    Dawg dawg;
    CHECK(dawg.loadFromMemory(bytes.data(), bytes.size()));
    CHECK(dawg.wordCount() == words.size());

    // Round trip: every word in the source list is found, IDs are dense
    // (cover exactly [0, wordCount)).
    std::vector<bool> idSeen(dawg.wordCount(), false);
    for (const std::string& w : words) {
        uint32_t id = 0;
        bool found = dawg.findWordId(w.c_str(), w.size(), &id);
        CHECK(found);
        if (!found) continue;
        CHECK(id < dawg.wordCount());
        CHECK(!idSeen[id]);
        idSeen[id] = true;
    }
    CHECK(std::all_of(idSeen.begin(), idSeen.end(), [](bool b) { return b; }));

    // Nothing else is found: sample random strings over the same alphabet
    // and length range and check any hit is actually in the source set.
    std::unordered_set<std::string> wordSet(words.begin(), words.end());
    std::mt19937 rng(12345);
    std::uniform_int_distribution<int> lenDist(2, static_cast<int>(built.maxWordLen));
    std::uniform_int_distribution<int> letterDist(0, 25);
    int falsePositives = 0;
    for (int i = 0; i < 20000; ++i) {
        int len = lenDist(rng);
        std::string s(static_cast<size_t>(len), 'A');
        for (char& c : s) c = static_cast<char>('A' + letterDist(rng));
        uint32_t id = 0;
        bool found = dawg.findWordId(s.c_str(), s.size(), &id);
        bool shouldBeFound = wordSet.count(s) != 0;
        if (found != shouldBeFound) ++falsePositives;
    }
    CHECK(falsePositives == 0);

    // wordForId inverts findWordId on a sample.
    char buf[64];
    std::uniform_int_distribution<size_t> idxDist(0, words.size() - 1);
    for (int i = 0; i < 5000; ++i) {
        const std::string& w = words[idxDist(rng)];
        uint32_t id = 0;
        CHECK(dawg.findWordId(w.c_str(), w.size(), &id));
        size_t len = dawg.wordForId(id, buf, sizeof(buf));
        CHECK(len == w.size());
        CHECK(std::string(buf, len) == w);
    }

    // Rebuilding from the same (sorted, deduped) list is byte-identical.
    BuiltDawg built2 = buildDawg(words);
    std::vector<uint8_t> bytes2 = serializeDawg(built2);
    CHECK(bytes == bytes2);
}

}  // namespace

int main(int argc, char** argv) {
    testSmallRoundTrip();
    testRebuildIsByteIdentical();
    testMinimizationSharesStates();

    if (argc > 1) {
        testFullDictionary(argv[1]);
    } else {
        std::fprintf(stderr, "note: pass a word-list path as argv[1] to also run the full-dictionary test\n");
    }

    std::fprintf(stderr, "%d/%d checks passed\n", g_checks - g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
