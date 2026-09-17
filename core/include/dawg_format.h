#pragma once

#include <cstddef>
#include <cstdint>

// On-disk / in-memory format for FluxCore's numbered DAWG (D1).
//
// Layout of the file (all integers little-endian, native on x86_64/arm64
// so no byte-swapping is done):
//
//   [0, kHeaderSize)                         HeaderFields, fixed 64 bytes
//   [kHeaderSize, +stateCount*8)             DawgState[stateCount]
//   [..., +edgeCount*4)                      DawgEdge[edgeCount] (uint32_t each)
//
// A "state" is a node of the minimized automaton; `rootState` (in the
// header) is the start state. Each state's outgoing edges occupy a
// contiguous run in the edge array starting at state.edgeStart and ending
// at (and including) the first edge with endOfList() set.
//
// Edge record, packed into a uint32_t:
//   bits 0..4   (5 bits)   letter, 0 = 'A' .. 25 = 'Z'
//   bit  5                 endOfWord: taking this edge completes a word
//   bit  6                 endOfList: last edge in the source state's run
//   bits 7..31  (25 bits)  index of the target state
//
// Numbering (perfect hash): state.wordCount is the number of distinct
// words whose remaining path starts at that state, i.e. for every
// outgoing edge e: (1 if e.endOfWord else 0) + targetState(e).wordCount,
// summed over all of the state's edges. This lets any word's dense
// integer ID be computed in O(word length) with no side table, and lets
// any ID be decoded back to a word the same way (see core/dawg.h).

namespace fluxcore::dawgformat {

constexpr uint32_t kMagic = 0x47574144u;  // bytes 'D','A','W','G' little-endian
constexpr uint32_t kVersion = 1;
constexpr size_t kHeaderSize = 64;

constexpr uint32_t kLetterBits = 5;
constexpr uint32_t kLetterMask = (1u << kLetterBits) - 1u;  // 0x1F
constexpr uint32_t kEndOfWordBit = kLetterBits;              // bit 5
constexpr uint32_t kEndOfListBit = kLetterBits + 1;          // bit 6
constexpr uint32_t kChildShift = kLetterBits + 2;            // bits 7..31

inline uint32_t packEdge(uint32_t letter, bool endOfWord, bool endOfList, uint32_t childState) {
    return (letter & kLetterMask) | (endOfWord ? (1u << kEndOfWordBit) : 0u) |
           (endOfList ? (1u << kEndOfListBit) : 0u) | (childState << kChildShift);
}

// Byte-exact header layout, read/written with memcpy (never reinterpret_cast
// directly over a raw buffer) so there is no dependency on compiler padding
// rules for the header specifically.
struct HeaderFields {
    uint32_t magic;
    uint32_t version;
    uint32_t wordCount;
    uint32_t stateCount;
    uint32_t edgeCount;
    uint32_t rootState;
    uint32_t maxWordLen;
    uint32_t padding0;
    uint64_t sourceHash;
    uint8_t reserved[24];
};
static_assert(sizeof(HeaderFields) == kHeaderSize, "HeaderFields must match kHeaderSize exactly");

}  // namespace fluxcore::dawgformat
