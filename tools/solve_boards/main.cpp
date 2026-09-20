#include "config_json.h"
#include "solver.h"
#include "thread_pool.h"

#include <cstdio>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

// Solves externally supplied boards -- the real ranked boards from a Flux
// export -- with the same solver the simulator uses, so observed-play
// analysis and simulated norms can never disagree about what a board holds.
//
// Input: one board per line, `id<TAB>LETTERS`, row-major, 16 or 25 letters.
// Output: one row per (board, distinct word):
//   id  word  pathCount  paths
// where `paths` is every stored path, comma-separated, each path written as
// one character per cell ('a' + cell index). pathCount is the true count and
// can exceed the stored paths when the config's maxPathsPerWord cap is hit.

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::SolveMode;
using fluxcore::SolveResult;
using fluxcore::Solver;
using namespace fluxtools;

namespace {

std::vector<uint8_t> readFile(const std::string& path, bool* ok) {
    std::ifstream in(path, std::ios::binary);
    if (!in) { *ok = false; return {}; }
    *ok = true;
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

struct InputBoard {
    std::string id;
    std::string letters;
};

}  // namespace

int main(int argc, char** argv) {
    if (argc < 5) {
        std::cerr << "usage: solve_boards <ruleset.json> <dawg> <boards.tsv> <out.tsv> [threads]\n";
        return 1;
    }
    unsigned threads = (argc > 5) ? static_cast<unsigned>(std::stoul(argv[5]))
                                  : std::thread::hardware_concurrency();
    if (threads == 0) threads = 1;

    fluxcore::config::LoadResult loaded;
    std::string error;
    if (!fluxcore::config::loadRulesetConfig(argv[1], &loaded, &error)) {
        std::cerr << "error: " << error << "\n";
        return 1;
    }
    bool ok = false;
    const std::vector<uint8_t> dawgBytes = readFile(argv[2], &ok);
    Dawg dawg;
    if (!ok || !dawg.loadFromMemory(dawgBytes.data(), dawgBytes.size())) {
        std::cerr << "error: cannot load DAWG " << argv[2] << "\n";
        return 1;
    }
    if (!fluxcore::config::enforceDictionary(loaded.config, dawg.sourceHash(), dawg.wordCount(),
                                             "solve_boards")) {
        return 1;
    }

    std::vector<InputBoard> boards;
    {
        std::ifstream in(argv[3]);
        if (!in) { std::cerr << "error: cannot read " << argv[3] << "\n"; return 1; }
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty()) continue;
            const size_t tab = line.find('\t');
            if (tab == std::string::npos) { std::cerr << "error: bad line: " << line << "\n"; return 1; }
            InputBoard b{line.substr(0, tab), line.substr(tab + 1)};
            if (b.letters.size() != 16 && b.letters.size() != 25) {
                std::cerr << "error: board " << b.id << " has " << b.letters.size() << " letters\n";
                return 1;
            }
            for (char c : b.letters) {
                if (c < 'A' || c > 'Z') { std::cerr << "error: board " << b.id << " not A-Z\n"; return 1; }
            }
            boards.push_back(std::move(b));
        }
    }

    std::vector<std::unique_ptr<Solver>> solvers;
    std::vector<SolveResult> scratch(threads);
    for (unsigned t = 0; t < threads; ++t) {
        solvers.push_back(std::make_unique<Solver>(dawg, loaded.config.scores, loaded.config.solver));
    }

    // Rendered per board and written in input order afterwards, so the file
    // does not depend on which thread solved which board.
    std::vector<std::string> rendered(boards.size());
    parallelFor(boards.size(), threads, [&](uint64_t index, unsigned t) {
        const InputBoard& in = boards[index];
        Board board;
        board.side = in.letters.size() == 16 ? 4 : 5;
        for (size_t i = 0; i < in.letters.size(); ++i) board.letters[i] = static_cast<uint8_t>(in.letters[i] - 'A');

        SolveResult& result = scratch[t];
        solvers[t]->solve(board, SolveMode::Full, &result);

        std::string out;
        char word[64];
        for (size_t w = 0; w < result.wordCount(); ++w) {
            const size_t len = dawg.wordForId(result.wordIds[w], word, sizeof(word));
            out += in.id;
            out += '\t';
            out.append(word, len);
            out += '\t';
            out += std::to_string(result.pathCounts[w]);
            out += '\t';
            const uint8_t* cells = &result.pathCells[result.pathOffsets[w]];
            for (uint32_t p = 0; p < result.storedPathCounts[w]; ++p) {
                if (p) out += ',';
                for (uint8_t k = 0; k < len; ++k) out += static_cast<char>('a' + cells[p * len + k]);
            }
            out += '\n';
        }
        rendered[index] = std::move(out);
    });

    std::ofstream out(argv[4], std::ios::binary);
    if (!out) { std::cerr << "error: cannot write " << argv[4] << "\n"; return 1; }
    out << "id\tword\tpathCount\tpaths\n";
    for (const std::string& s : rendered) out << s;
    std::fprintf(stderr, "solve_boards: %zu boards, config %016llx, dictionary %u words\n", boards.size(),
                 static_cast<unsigned long long>(loaded.config.configHash), dawg.wordCount());
    return 0;
}
