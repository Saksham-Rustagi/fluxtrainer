// Builds every lexicon index against a real dictionary and prints what each
// one cost and what it found. This is where the D5 numbers in the report come
// from; it is not part of any measurement pipeline.

#include "affix.h"
#include "config_json.h"
#include "lexicon.h"

#include <sys/resource.h>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

using fluxcore::AffixClass;
using fluxcore::Dawg;
namespace lex = fluxcore::lex;

namespace {

std::vector<uint8_t> readFile(const std::string& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) return {};
    const std::streamsize size = in.tellg();
    in.seekg(0);
    std::vector<uint8_t> bytes(static_cast<size_t>(size));
    if (!in.read(reinterpret_cast<char*>(bytes.data()), size)) return {};
    return bytes;
}

double peakRssMB() {
    rusage usage{};
    getrusage(RUSAGE_SELF, &usage);
    // Darwin reports ru_maxrss in bytes, Linux in kilobytes.
#ifdef __APPLE__
    return static_cast<double>(usage.ru_maxrss) / (1024.0 * 1024.0);
#else
    return static_cast<double>(usage.ru_maxrss) / 1024.0;
#endif
}

void printStats(const char* name, const lex::IndexStats& stats) {
    std::printf("  %-18s %10zu entries  %8.1f ms  %7.1f MB held  %7.1f MB peak\n", name,
                stats.entries, stats.buildMillis, stats.bytes / 1048576.0,
                stats.peakBytes / 1048576.0);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: lexstat <dictionary.dawg> [ruleset.json]\n");
        return 1;
    }
    const std::vector<uint8_t> bytes = readFile(argv[1]);
    Dawg dawg;
    if (bytes.empty() || !dawg.loadFromMemory(bytes.data(), bytes.size())) {
        std::fprintf(stderr, "error: cannot load DAWG from %s\n", argv[1]);
        return 1;
    }
    std::printf("dictionary: %u words, max length %u, source hash %016llx\n\n", dawg.wordCount(),
                dawg.maxWordLen(), static_cast<unsigned long long>(dawg.sourceHash()));

    lex::AnagramIndex anagrams;
    anagrams.build(dawg);
    std::printf("anagram index\n");
    printStats("classes", anagrams.stats());
    std::printf("  %zu classes with 2+ members, %zu directed pairs, largest class %zu\n\n",
                anagrams.nonTrivialClassCount(), anagrams.pairCount(),
                anagrams.largestClassSize());

    lex::SubwordIndex subwords;
    subwords.build(dawg, lex::SubwordOptions{});
    std::printf("subword indices (minSubwordLen 3)\n");
    printStats("drop-terminal", subwords.terminalStats());
    printStats("drop-interior", subwords.interiorStats());
    printStats("additive ext", subwords.extensionStats());
    std::printf("  %zu stems have at least one extension\n", subwords.stemsWithExtensions());

    // Splits worth naming separately in the report. An entry is one (word,
    // sub, split); a stem occurring twice in one word makes two entries out of
    // one word pair, so the distinct pair count is the smaller number.
    size_t frontOnly = 0, backOnly = 0, bothEnds = 0;
    std::vector<uint64_t> distinct;
    distinct.reserve(subwords.dropTerminalPairs().size());
    std::vector<bool> hasTerminal(dawg.wordCount(), false);
    for (const lex::DropTerminalPair& pair : subwords.dropTerminalPairs()) {
        if (pair.trimFront != 0 && pair.trimBack != 0) ++bothEnds;
        else if (pair.trimFront != 0) ++frontOnly;
        else ++backOnly;
        distinct.push_back((static_cast<uint64_t>(pair.word) << 32) | pair.sub);
        hasTerminal[pair.word] = true;
    }
    std::sort(distinct.begin(), distinct.end());
    distinct.erase(std::unique(distinct.begin(), distinct.end()), distinct.end());
    std::vector<bool> hasInterior(dawg.wordCount(), false);
    for (const lex::DropInteriorPair& pair : subwords.dropInteriorPairs()) {
        hasInterior[pair.word] = true;
    }
    std::printf("  drop-terminal by trim: %zu back-only, %zu front-only, %zu both ends\n",
                backOnly, frontOnly, bothEnds);
    std::printf("  %zu distinct (word, sub) drop-terminal pairs\n", distinct.size());
    std::printf("  %zu words have a drop-terminal sub-word, %zu have a drop-interior one\n\n",
                static_cast<size_t>(std::count(hasTerminal.begin(), hasTerminal.end(), true)),
                static_cast<size_t>(std::count(hasInterior.begin(), hasInterior.end(), true)));

    for (const auto& bounds : std::vector<std::pair<uint8_t, uint8_t>>{{4, 7}, {2, 7}}) {
        lex::StemFamilyIndex families;
        lex::FamilyOptions options;
        options.minStemLen = bounds.first;
        options.maxStemLen = bounds.second;
        std::string error;
        if (!families.build(dawg, options, &error)) {
            std::fprintf(stderr, "family build failed: %s\n", error.c_str());
            return 1;
        }
        std::printf("stem families %u..%u, minFamilySize %u\n", options.minStemLen,
                    options.maxStemLen, options.minFamilySize);
        printStats("families", families.stats());
        std::printf("  %zu member slots across %zu families\n\n", families.memberSlots(),
                    families.familyCount());
    }

    // Spec 7.3 mechanism 3: the affix ALPHABET, mined from the dictionary.
    // No list anywhere -- these are the continuations CSW21 actually uses,
    // ranked by how many distinct stems each one extends.
    lex::MinedAffixSet mined;
    lex::MinedAffixOptions minedOptions;
    mined.build(dawg, subwords, minedOptions);
    std::printf("\nmined affix alphabet (7.3): top %zu back, top %zu front, %.0f ms\n",
                mined.back().size(), mined.front().size(), mined.stats().buildMillis);
    std::printf("  back : ");
    for (size_t i = 0; i < mined.back().size(); ++i) {
        const auto& a = mined.back()[i];
        std::printf("%s-%s(%u)", i ? " " : "", std::string(a.letters, a.len).c_str(), a.stems);
    }
    std::printf("\n  front: ");
    for (size_t i = 0; i < mined.front().size(); ++i) {
        const auto& a = mined.front()[i];
        std::printf("%s%s-(%u)", i ? " " : "", std::string(a.letters, a.len).c_str(), a.stems);
    }
    std::printf("\n");

    return 0;
}
