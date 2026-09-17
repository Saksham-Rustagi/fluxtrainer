#pragma once

#include <cstddef>
#include <cstdint>

#include "dawg_format.h"

// Runtime (in-app / solver) side of the numbered DAWG. See dawg_format.h
// for the exact on-disk bit layout.
//
// This type does no I/O and touches no platform API: it is a zero-copy
// reader over a caller-supplied buffer (e.g. the result of mmap()), which
// keeps it safe to compile into the iOS core static library. Opening the
// file and mapping it into memory is the caller's job (tools/ today, the
// app's board-load path later).

namespace fluxcore {

struct DawgEdge {
    uint32_t raw;

    uint32_t letter() const { return raw & dawgformat::kLetterMask; }
    bool endOfWord() const { return (raw >> dawgformat::kEndOfWordBit) & 1u; }
    bool endOfList() const { return (raw >> dawgformat::kEndOfListBit) & 1u; }
    uint32_t childState() const { return raw >> dawgformat::kChildShift; }
};
static_assert(sizeof(DawgEdge) == 4, "DawgEdge must be a single packed uint32_t");

struct DawgState {
    uint32_t edgeStart;
    uint32_t wordCount;
};
static_assert(sizeof(DawgState) == 8, "DawgState must be two packed uint32_t fields, no padding");

struct DawgHeader {
    uint32_t magic = 0;
    uint32_t version = 0;
    uint32_t wordCount = 0;
    uint32_t stateCount = 0;
    uint32_t edgeCount = 0;
    uint32_t rootState = 0;
    uint32_t maxWordLen = 0;
    uint64_t sourceHash = 0;
};

class Dawg {
public:
    Dawg() = default;

    // Validates the header and wires up internal pointers into `data`.
    // Returns false (leaving the Dawg unloaded) if the buffer is too small,
    // the magic/version don't match, or the sizes in the header don't fit
    // inside `size` bytes. The caller must keep `data` alive for as long as
    // this Dawg (and anything reading from it) is in use.
    bool loadFromMemory(const uint8_t* data, size_t size);

    bool isLoaded() const { return data_ != nullptr; }

    const DawgHeader& header() const { return header_; }
    uint32_t wordCount() const { return header_.wordCount; }
    uint32_t stateCount() const { return header_.stateCount; }
    uint32_t edgeCount() const { return header_.edgeCount; }
    uint32_t rootState() const { return header_.rootState; }
    uint32_t maxWordLen() const { return header_.maxWordLen; }
    uint64_t sourceHash() const { return header_.sourceHash; }

    const DawgState& state(uint32_t stateIndex) const { return states_[stateIndex]; }
    const DawgEdge& edge(uint32_t edgeIndex) const { return edges_[edgeIndex]; }

    // A state's wordCount is 0 exactly when it has no outgoing edges, which
    // is also the only case where its edgeStart does not point at a real,
    // end-of-list-terminated edge run. Anything walking the graph must check
    // this before scanning a state's edges.
    bool hasEdges(uint32_t stateIndex) const { return states_[stateIndex].wordCount != 0; }

    // Looks up `word` (uppercase A-Z, `len` bytes, need not be
    // NUL-terminated). Returns true and writes the dense word ID to
    // `outId` if `word` is in the dictionary.
    bool findWordId(const char* word, size_t len, uint32_t* outId) const;

    // Inverse of findWordId: writes the word for `id` into `outBuf` (which
    // must hold at least maxWordLen() bytes; it is not NUL-terminated).
    // Returns the word's length, or 0 if `id` is out of range or `outBuf`
    // is too small.
    size_t wordForId(uint32_t id, char* outBuf, size_t outBufSize) const;

private:
    const uint8_t* data_ = nullptr;
    size_t size_ = 0;
    DawgHeader header_{};
    const DawgState* states_ = nullptr;
    const DawgEdge* edges_ = nullptr;
};

}  // namespace fluxcore
