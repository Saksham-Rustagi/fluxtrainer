#include "dawg_builder.h"

#include "dawg_format.h"

#include <algorithm>
#include <cassert>
#include <cstring>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace fluxcore::build {
namespace {

using dawgformat::packEdge;

// A state still under construction: its transition list may still grow
// (more words sharing its prefix haven't been seen yet) until the
// builder decides to freeze it.
struct TempState {
    std::vector<std::pair<uint8_t, int32_t>> trans;  // (letter 0-25, child temp id); built in sorted order
    bool final = false;
};

// Runs one Daciuk-style incremental-minimization pass over `words_`.
// Standard algorithm (Daciuk, Mihov, Watson & Watson 2000): walk the
// sorted list, and every time a word diverges from the previous one after
// `commonLen` shared characters, freeze (minimize-or-reuse) every temp
// state deeper than `commonLen` on the previous word's path -- those
// states can never be extended again because the input is sorted -- then
// grow new temp states for the new word's suffix.
class Builder {
public:
    explicit Builder(const std::vector<std::string>& sortedWords) : words_(sortedWords) {}

    BuiltDawg run() {
        validate();

        temp_.emplace_back();  // root = temp id 0
        std::vector<int32_t> path{0};
        std::string previousWord;

        for (const std::string& word : words_) {
            size_t commonLen = commonPrefixLen(previousWord, word);
            freezeSuffix(path, commonLen);
            extendPath(path, commonLen, word);
            temp_[path.back()].final = true;
            previousWord = word;
            maxWordLen_ = std::max(maxWordLen_, static_cast<uint32_t>(word.size()));
        }
        // freezeSuffix(path, 0) leaves path[0] (the root) itself unfrozen --
        // that's the correct behavior mid-loop (root may still gain new
        // branches), but here it's the last word, so freeze the root too.
        freezeSuffix(path, 0);
        freezeState(path[0]);

        BuiltDawg out;
        out.stateEdgeStart = std::move(edgeStart_);
        out.stateWordCount = std::move(wordCount_);
        out.edges = std::move(edges_);
        out.maxWordLen = maxWordLen_;
        out.sourceHash = hashWordList(words_);
        out.rootState = tempToFrozen_.at(0);
        out.wordCount = out.stateWordCount[out.rootState];

        if (out.wordCount != words_.size()) {
            throw std::runtime_error("dawg builder: word count mismatch after build (got " +
                                      std::to_string(out.wordCount) + ", expected " +
                                      std::to_string(words_.size()) + ")");
        }
        return out;
    }

private:
    void validate() const {
        if (words_.empty()) throw std::runtime_error("dawg builder: empty word list");
        for (size_t i = 0; i < words_.size(); ++i) {
            const std::string& w = words_[i];
            if (w.empty()) throw std::runtime_error("dawg builder: empty word in list");
            for (char c : w) {
                if (c < 'A' || c > 'Z') {
                    throw std::runtime_error("dawg builder: non A-Z character in word: " + w);
                }
            }
            if (i > 0 && !(words_[i - 1] < words_[i])) {
                throw std::runtime_error("dawg builder: word list not sorted/deduped at: " + w);
            }
        }
    }

    static size_t commonPrefixLen(const std::string& a, const std::string& b) {
        size_t n = std::min(a.size(), b.size());
        size_t i = 0;
        while (i < n && a[i] == b[i]) ++i;
        return i;
    }

    // Freezes path[size-1] .. path[downTo+1], bottom-up, truncating `path`
    // to length downTo+1.
    void freezeSuffix(std::vector<int32_t>& path, size_t downTo) {
        while (path.size() > downTo + 1) {
            int32_t tempId = path.back();
            path.pop_back();
            freezeState(tempId);
        }
    }

    void extendPath(std::vector<int32_t>& path, size_t commonLen, const std::string& word) {
        int32_t cur = path[commonLen];
        for (size_t i = commonLen; i < word.size(); ++i) {
            uint8_t letter = static_cast<uint8_t>(word[i] - 'A');
            temp_.emplace_back();
            int32_t childTemp = static_cast<int32_t>(temp_.size() - 1);
            temp_[cur].trans.emplace_back(letter, childTemp);
            path.push_back(childTemp);
            cur = childTemp;
        }
    }

    // Freezes temp state `tempId`: every child it transitions to must
    // already be frozen (guaranteed by freeze order). Reuses an existing
    // equivalent frozen state if the register already has one, otherwise
    // allocates a new one and computes its word count.
    void freezeState(int32_t tempId) {
        TempState& st = temp_[tempId];

        std::string sig;
        sig.reserve(1 + st.trans.size() * 5);
        sig.push_back(st.final ? '1' : '0');
        for (auto& [letter, childTemp] : st.trans) {
            uint32_t frozenChild = tempToFrozen_.at(childTemp);
            sig.push_back(static_cast<char>(letter));
            sig.append(reinterpret_cast<const char*>(&frozenChild), sizeof(frozenChild));
        }

        auto regIt = register_.find(sig);
        if (regIt != register_.end()) {
            tempToFrozen_[tempId] = regIt->second;
            return;
        }

        uint32_t stateId = static_cast<uint32_t>(edgeStart_.size());
        edgeStart_.push_back(static_cast<uint32_t>(edges_.size()));

        uint32_t wc = 0;
        for (size_t i = 0; i < st.trans.size(); ++i) {
            auto [letter, childTemp] = st.trans[i];
            uint32_t frozenChild = tempToFrozen_.at(childTemp);
            bool endOfWord = temp_[childTemp].final;
            bool endOfList = (i + 1 == st.trans.size());
            edges_.push_back(packEdge(letter, endOfWord, endOfList, frozenChild));
            wc += (endOfWord ? 1u : 0u) + wordCount_[frozenChild];
        }
        wordCount_.push_back(wc);

        register_.emplace(std::move(sig), stateId);
        tempToFrozen_[tempId] = stateId;
    }

    const std::vector<std::string>& words_;
    std::vector<TempState> temp_;
    std::unordered_map<int32_t, uint32_t> tempToFrozen_;
    std::unordered_map<std::string, uint32_t> register_;

    std::vector<uint32_t> edgeStart_;
    std::vector<uint32_t> wordCount_;
    std::vector<uint32_t> edges_;
    uint32_t maxWordLen_ = 0;
};

}  // namespace

BuiltDawg buildDawg(const std::vector<std::string>& sortedWords) {
    Builder builder(sortedWords);
    return builder.run();
}

uint64_t hashWordList(const std::vector<std::string>& sortedWords) {
    uint64_t h = 1469598103934665603ull;  // FNV-1a 64-bit offset basis
    constexpr uint64_t prime = 1099511628211ull;
    auto mix = [&](unsigned char c) {
        h ^= c;
        h *= prime;
    };
    for (const std::string& w : sortedWords) {
        for (char c : w) mix(static_cast<unsigned char>(c));
        mix('\n');
    }
    return h;
}

std::vector<uint8_t> serializeDawg(const BuiltDawg& dawg) {
    using namespace dawgformat;

    size_t stateCount = dawg.stateEdgeStart.size();
    size_t edgeCount = dawg.edges.size();
    size_t total = kHeaderSize + stateCount * sizeof(uint32_t) * 2 + edgeCount * sizeof(uint32_t);

    std::vector<uint8_t> bytes(total, 0);

    HeaderFields hdr{};
    hdr.magic = kMagic;
    hdr.version = kVersion;
    hdr.wordCount = dawg.wordCount;
    hdr.stateCount = static_cast<uint32_t>(stateCount);
    hdr.edgeCount = static_cast<uint32_t>(edgeCount);
    hdr.rootState = dawg.rootState;
    hdr.maxWordLen = dawg.maxWordLen;
    hdr.sourceHash = dawg.sourceHash;
    std::memcpy(bytes.data(), &hdr, sizeof(hdr));

    size_t offset = kHeaderSize;
    for (size_t i = 0; i < stateCount; ++i) {
        std::memcpy(bytes.data() + offset, &dawg.stateEdgeStart[i], sizeof(uint32_t));
        offset += sizeof(uint32_t);
        std::memcpy(bytes.data() + offset, &dawg.stateWordCount[i], sizeof(uint32_t));
        offset += sizeof(uint32_t);
    }
    if (edgeCount > 0) {
        std::memcpy(bytes.data() + offset, dawg.edges.data(), edgeCount * sizeof(uint32_t));
        offset += edgeCount * sizeof(uint32_t);
    }
    assert(offset == total);
    return bytes;
}

}  // namespace fluxcore::build
