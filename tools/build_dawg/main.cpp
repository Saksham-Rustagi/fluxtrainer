#include "dawg_builder.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
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
    if (argc < 3) {
        std::cerr << "usage: build_dawg <word-list-path> <output-path>\n";
        return 1;
    }
    std::string inputPath = argv[1];
    std::string outputPath = argv[2];

    auto t0 = std::chrono::steady_clock::now();
    std::vector<std::string> words = loadWordList(inputPath);
    if (words.empty()) {
        std::cerr << "error: no valid words loaded from " << inputPath << "\n";
        return 1;
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
