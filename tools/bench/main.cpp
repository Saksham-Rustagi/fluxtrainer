#include "solver.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <numeric>
#include <random>
#include <string>
#include <vector>

using fluxcore::Board;
using fluxcore::Dawg;
using fluxcore::ScoreTable;
using fluxcore::SolveMode;
using fluxcore::SolveResult;
using fluxcore::Solver;

namespace {

// Spec 2.2. Duplicated here rather than shared with the solver because the
// real table is ruleset config (D3); this is a benchmark harness, not a
// generation path.
ScoreTable specScoreTable() {
    ScoreTable table;
    for (uint8_t len = 0; len <= fluxcore::kMaxCells; ++len) {
        uint32_t points = 0;
        if (len == 3) points = 100;
        else if (len == 4) points = 400;
        else if (len == 5) points = 800;
        else if (len >= 6) points = 1400 + 400 * (len - 6);
        table.pointsByLength[len] = points;
    }
    return table;
}

std::vector<uint8_t> readFile(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::cerr << "error: cannot open " << path << "\n";
        std::exit(1);
    }
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

Board boardFromString(uint8_t side, const std::string& letters) {
    Board board;
    board.side = side;
    for (size_t i = 0; i < letters.size() && i < fluxcore::kMaxCells; ++i) {
        board.letters[i] = static_cast<uint8_t>(std::toupper(letters[i]) - 'A');
    }
    return board;
}

// Rough English letter frequency, used ONLY to make benchmark boards denser
// than uniform random so the timings mean something. This is not a
// generation parameter -- the real distribution is ruleset config (D3), and
// no statistic is derived from these boards.
const int kBenchWeights[26] = {78, 20, 40, 38, 110, 14, 30, 23, 86, 2,  9,  53, 27,
                               72, 61, 28, 2,  73,  87, 67, 33, 10, 9,  3,  16, 4};

struct Timing {
    double p50 = 0, p95 = 0, max = 0, mean = 0;
};

Timing summarize(std::vector<double>& samples) {
    Timing t;
    std::sort(samples.begin(), samples.end());
    t.p50 = samples[samples.size() / 2];
    t.p95 = samples[static_cast<size_t>(samples.size() * 0.95)];
    t.max = samples.back();
    t.mean = std::accumulate(samples.begin(), samples.end(), 0.0) / samples.size();
    return t;
}

struct Outcome {
    Timing timing;
    double meanWords = 0;
    double meanPaths = 0;
    double meanPoints = 0;
};

Outcome benchBoards(Solver& solver, const std::vector<Board>& boards, SolveMode mode) {
    SolveResult result;
    std::vector<double> samples;
    samples.reserve(boards.size());
    double words = 0, paths = 0, points = 0;

    for (const Board& board : boards) {
        const auto start = std::chrono::steady_clock::now();
        solver.solve(board, mode, &result);
        const auto end = std::chrono::steady_clock::now();
        samples.push_back(std::chrono::duration<double, std::micro>(end - start).count());
        words += static_cast<double>(result.wordCount());
        points += static_cast<double>(result.totalPoints);
        for (uint32_t c : result.pathCounts) paths += c;
    }

    Outcome outcome;
    outcome.timing = summarize(samples);
    outcome.meanWords = words / boards.size();
    outcome.meanPaths = paths / boards.size();
    outcome.meanPoints = points / boards.size();
    return outcome;
}

std::vector<Board> randomBoards(uint8_t side, size_t count, bool weighted, uint64_t seed) {
    std::mt19937_64 rng(seed);
    std::discrete_distribution<int> weightedDist(std::begin(kBenchWeights), std::end(kBenchWeights));
    std::uniform_int_distribution<int> uniformDist(0, 25);

    std::vector<Board> boards(count);
    for (Board& board : boards) {
        board.side = side;
        for (uint8_t c = 0; c < board.cellCount(); ++c) {
            board.letters[c] = static_cast<uint8_t>(weighted ? weightedDist(rng) : uniformDist(rng));
        }
    }
    return boards;
}

void printRow(const char* label, const Outcome& outcome) {
    std::printf("  %-28s %8.1f %8.1f %8.1f   %7.1f %8.1f %9.0f\n", label, outcome.timing.p50,
                outcome.timing.p95, outcome.timing.max, outcome.meanWords, outcome.meanPaths,
                outcome.meanPoints);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: bench <dawg-path> [boards-per-case]\n";
        return 1;
    }
    const std::vector<uint8_t> bytes = readFile(argv[1]);
    const size_t perCase = (argc > 2) ? static_cast<size_t>(std::stoul(argv[2])) : 2000;

    Dawg dawg;
    if (!dawg.loadFromMemory(bytes.data(), bytes.size())) {
        std::cerr << "error: not a valid DAWG file: " << argv[1] << "\n";
        return 1;
    }
    std::printf("dawg: %u words, %u states, %u edges\n\n", dawg.wordCount(), dawg.stateCount(),
                dawg.edgeCount());

    Solver solver(dawg, specScoreTable());

    std::printf("solve time (microseconds), single-threaded, release\n");
    std::printf("  %-28s %8s %8s %8s   %7s %8s %9s\n", "case", "p50", "p95", "max", "words",
                "paths", "points");

    for (const uint8_t side : {4, 5}) {
        for (const bool weighted : {false, true}) {
            const std::vector<Board> boards = randomBoards(side, perCase, weighted, 0xF10C + side);
            for (const SolveMode mode : {SolveMode::Count, SolveMode::Full}) {
                char label[64];
                std::snprintf(label, sizeof(label), "%dx%d %s %s", side, side,
                              weighted ? "weighted" : "uniform ",
                              mode == SolveMode::Count ? "count" : "full ");
                printRow(label, benchBoards(solver, boards, mode));
            }
        }
    }

    // A dense real board: LetterCounter's best 4x4 from a 35M-board search.
    // Worst-case stress rather than a typical board.
    const std::vector<Board> dense(perCase, boardFromString(4, "SEMCNAPAGIRSSELC"));
    printRow("4x4 dense (known board) count", benchBoards(solver, dense, SolveMode::Count));
    printRow("4x4 dense (known board) full ", benchBoards(solver, dense, SolveMode::Full));

    return 0;
}
