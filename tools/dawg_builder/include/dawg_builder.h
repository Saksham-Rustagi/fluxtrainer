#pragma once

#include <cstdint>
#include <string>
#include <vector>

// Offline (tools/) side of the numbered DAWG: builds one from a sorted
// word list via Daciuk-style incremental minimization, and serializes it
// to the exact byte layout core/include/dawg_format.h reads. None of this
// links into core/ -- it's build-tool logic, not engine code.

namespace fluxcore::build {

struct BuiltDawg {
    std::vector<uint32_t> stateEdgeStart;  // per state, index into `edges`
    std::vector<uint32_t> stateWordCount;  // per state, words reachable from it
    std::vector<uint32_t> edges;           // packed DawgEdge values, see dawg_format.h
    uint32_t rootState = 0;
    uint32_t wordCount = 0;
    uint32_t maxWordLen = 0;
    uint64_t sourceHash = 0;
};

// Builds a minimal DAWG from `sortedWords`. Preconditions (checked, throws
// std::runtime_error on violation rather than silently coping): non-empty,
// every entry uppercase A-Z only, strictly ascending with no duplicates.
// Normalizing raw input (case-folding, sorting, deduping) is the caller's
// job -- see tools/build_dawg/main.cpp -- so this function stays testable
// against hand-written fixtures without re-deriving that logic.
BuiltDawg buildDawg(const std::vector<std::string>& sortedWords);

// FNV-1a 64-bit over the words joined by '\n'. Used as the header's
// sourceHash so a loader can detect it was handed a DAWG built from a
// different word list than it expects.
uint64_t hashWordList(const std::vector<std::string>& sortedWords);

// Serializes `dawg` to the exact on-disk bytes core/include/dawg.h loads
// with loadFromMemory(). Writing them to a file is the caller's job.
std::vector<uint8_t> serializeDawg(const BuiltDawg& dawg);

}  // namespace fluxcore::build
