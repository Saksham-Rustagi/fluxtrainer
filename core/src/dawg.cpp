#include "dawg.h"

#include <cstring>

namespace fluxcore {

using namespace dawgformat;

bool Dawg::loadFromMemory(const uint8_t* data, size_t size) {
    data_ = nullptr;
    size_ = 0;
    states_ = nullptr;
    edges_ = nullptr;
    header_ = DawgHeader{};

    if (data == nullptr || size < kHeaderSize) return false;

    HeaderFields hdr{};
    std::memcpy(&hdr, data, sizeof(hdr));
    if (hdr.magic != kMagic || hdr.version != kVersion) return false;
    if (hdr.stateCount == 0 || hdr.rootState >= hdr.stateCount) return false;

    size_t expected = kHeaderSize + static_cast<size_t>(hdr.stateCount) * sizeof(DawgState) +
                       static_cast<size_t>(hdr.edgeCount) * sizeof(DawgEdge);
    if (size < expected) return false;

    header_.magic = hdr.magic;
    header_.version = hdr.version;
    header_.wordCount = hdr.wordCount;
    header_.stateCount = hdr.stateCount;
    header_.edgeCount = hdr.edgeCount;
    header_.rootState = hdr.rootState;
    header_.maxWordLen = hdr.maxWordLen;
    header_.sourceHash = hdr.sourceHash;

    states_ = reinterpret_cast<const DawgState*>(data + kHeaderSize);
    edges_ = reinterpret_cast<const DawgEdge*>(data + kHeaderSize +
                                                static_cast<size_t>(hdr.stateCount) * sizeof(DawgState));
    data_ = data;
    size_ = size;
    return true;
}

bool Dawg::findWordId(const char* word, size_t len, uint32_t* outId) const {
    if (!isLoaded() || len == 0) return false;

    uint32_t state = header_.rootState;
    uint32_t id = 0;

    for (size_t i = 0; i < len; ++i) {
        if (!hasEdges(state)) return false;  // dead end, nothing can continue

        char c = word[i];
        if (c < 'A' || c > 'Z') return false;
        uint32_t letter = static_cast<uint32_t>(c - 'A');

        uint32_t edgeIdx = states_[state].edgeStart;
        bool matched = false;
        for (;;) {
            if (edgeIdx >= header_.edgeCount) return false;
            const DawgEdge& e = edges_[edgeIdx];
            if (e.letter() == letter) {
                bool isLastChar = (i + 1 == len);
                if (isLastChar) {
                    if (!e.endOfWord()) return false;
                    *outId = id;
                    return true;
                }
                if (e.endOfWord()) id += 1;
                state = e.childState();
                matched = true;
                break;
            }
            id += (e.endOfWord() ? 1u : 0u) + states_[e.childState()].wordCount;
            if (e.endOfList()) break;
            ++edgeIdx;
        }
        if (!matched) return false;
    }
    return false;  // len == 0 handled above; every other path returns inside the loop
}

size_t Dawg::wordForId(uint32_t id, char* outBuf, size_t outBufSize) const {
    if (!isLoaded() || id >= header_.wordCount) return 0;

    uint32_t state = header_.rootState;
    size_t len = 0;

    for (;;) {
        uint32_t edgeIdx = states_[state].edgeStart;
        bool advanced = false;
        for (;;) {
            if (edgeIdx >= header_.edgeCount) return 0;
            const DawgEdge& e = edges_[edgeIdx];
            uint32_t childCount = states_[e.childState()].wordCount;
            uint32_t count = (e.endOfWord() ? 1u : 0u) + childCount;
            if (id < count) {
                if (len >= outBufSize) return 0;
                outBuf[len++] = static_cast<char>('A' + e.letter());
                if (e.endOfWord()) {
                    if (id == 0) return len;
                    id -= 1;
                }
                state = e.childState();
                advanced = true;
                break;
            }
            id -= count;
            if (e.endOfList()) return 0;  // id out of range; shouldn't happen given the bound check above
            ++edgeIdx;
        }
        if (!advanced) return 0;
    }
}

}  // namespace fluxcore
