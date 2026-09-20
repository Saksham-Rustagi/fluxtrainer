#include "dawg_builder.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>

using namespace fluxcore::build;

namespace {

std::vector<std::string> loadWordList(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        std::cerr << "error: cannot open word list: " << path << "\n";
        std::exit(1);
    }
    std::vector<std::string> words;
    std::string line;
    size_t skipped = 0;
    while (std::getline(in, line)) {
        while (!line.empty() && (line.back() == '\r' || std::isspace(static_cast<unsigned char>(line.back())))) {
            line.pop_back();
        }
        if (line.empty()) continue;
        for (char& c : line) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        bool valid = std::all_of(line.begin(), line.end(), [](char c) { return c >= 'A' && c <= 'Z'; });
        if (!valid) {
            ++skipped;
            continue;
        }
        words.push_back(std::move(line));
    }
    if (skipped > 0) {
        std::cerr << "warning: skipped " << skipped << " non A-Z entries\n";
    }
    std::sort(words.begin(), words.end());
    words.erase(std::unique(words.begin(), words.end()), words.end());
    return words;
}

}  // namespace

int main(int argc, char** argv) {
    // Positional input/output, plus the two filters that turn CSW21 into the
    // Flux dictionary (spec 2.1): --exclude drops the words Flux removed, and
    // --max-letter-repeat drops every word needing more copies of one letter
    // than the ruleset's letter cap allows -- such a word can never have a
    // path on a capped board, so keeping it only inflates the word ID space.
    std::vector<std::string> positional;
    std::vector<std::string> excludePaths;
    size_t maxLetterRepeat = 0;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--exclude" && i + 1 < argc) {
            excludePaths.push_back(argv[++i]);
        } else if (arg == "--max-letter-repeat" && i + 1 < argc) {
            maxLetterRepeat = static_cast<size_t>(std::stoul(argv[++i]));
        } else {
            positional.push_back(arg);
        }
    }
    if (positional.size() != 2) {
        std::cerr << "usage: build_dawg <word-list-path> <output-path> [--exclude <word-list>]... "
                     "[--max-letter-repeat N]\n";
        return 1;
    }
    std::string inputPath = positional[0];
    std::string outputPath = positional[1];

    auto t0 = std::chrono::steady_clock::now();
    std::vector<std::string> words = loadWordList(inputPath);
    if (words.empty()) {
        std::cerr << "error: no valid words loaded from " << inputPath << "\n";
        return 1;
    }
    const size_t loadedCount = words.size();

    for (const std::string& path : excludePaths) {
        const std::vector<std::string> excluded = loadWordList(path);
        std::vector<std::string> kept;
        kept.reserve(words.size());
        std::set_difference(words.begin(), words.end(), excluded.begin(), excluded.end(),
                            std::back_inserter(kept));
        size_t absent = 0;
        for (const std::string& word : excluded) {
            if (!std::binary_search(words.begin(), words.end(), word)) ++absent;
        }
        std::cout << "excluded:       " << (words.size() - kept.size()) << " words listed in "
                  << path << "\n";
        if (absent > 0) {
            // An exclusion that matches nothing is a sign the lists disagree
            // on edition or spelling, which is worth failing loudly on.
            std::cerr << "error: " << absent << " words in " << path << " are not in "
                      << inputPath << "\n";
            return 1;
        }
        words = std::move(kept);
    }
    const size_t afterExclude = words.size();

    if (maxLetterRepeat > 0) {
        words.erase(std::remove_if(words.begin(), words.end(),
                                   [&](const std::string& word) {
                                       size_t counts[26] = {};
                                       for (char c : word) {
                                           if (++counts[c - 'A'] > maxLetterRepeat) return true;
                                       }
                                       return false;
                                   }),
                    words.end());
        std::cout << "letter cap:     " << (afterExclude - words.size()) << " words need more than "
                  << maxLetterRepeat << " of one letter and were pruned\n";
    }
    if (loadedCount != words.size()) {
        std::cout << "input words:    " << loadedCount << " -> " << words.size() << "\n";
    }
    auto t1 = std::chrono::steady_clock::now();

    BuiltDawg built;
    try {
        built = buildDawg(words);
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    auto t2 = std::chrono::steady_clock::now();

    std::vector<uint8_t> bytes = serializeDawg(built);
    auto t3 = std::chrono::steady_clock::now();

    std::ofstream out(outputPath, std::ios::binary);
    if (!out) {
        std::cerr << "error: cannot write output: " << outputPath << "\n";
        return 1;
    }
    out.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    out.close();

    double loadMs = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double buildMs = std::chrono::duration<double, std::milli>(t2 - t1).count();
    double serializeMs = std::chrono::duration<double, std::milli>(t3 - t2).count();

    size_t stateCount = built.stateEdgeStart.size();
    size_t edgeCount = built.edges.size();
    double mb = static_cast<double>(bytes.size()) / (1024.0 * 1024.0);

    std::cout << std::fixed << std::setprecision(2);
    std::cout << "words:          " << words.size() << "\n"
              << "states:         " << stateCount << "\n"
              << "edges:          " << edgeCount << "\n"
              << "max word len:   " << built.maxWordLen << "\n"
              << "output bytes:   " << bytes.size() << " (" << mb << " MB)\n"
              << "load time:      " << loadMs << " ms\n"
              << "build time:     " << buildMs << " ms\n"
              << "serialize time: " << serializeMs << " ms\n"
              << "source hash:    0x" << std::hex << built.sourceHash << std::dec << "\n"
              << "output:         " << outputPath << "\n";

    if (bytes.size() > 1024ull * 1024ull) {
        std::cout << "\nNOTE: output exceeds the <1 MB target in docs/Phase 1 build prompt.md D1.\n";
    }
    return 0;
}
