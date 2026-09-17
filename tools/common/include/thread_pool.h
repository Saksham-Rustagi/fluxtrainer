#pragma once

#include <cstdint>
#include <functional>

namespace fluxtools {

// Runs body(index, threadId) for every index in [0, count). Indices are pulled
// from a shared atomic counter rather than striped, so one expensive board
// cannot stall a whole worker's share.
//
// Which thread picks up which index deliberately does not affect results:
// every board's RNG stream is derived from its index (see deriveBoardSeed),
// and all aggregation is order-independent. That is what lets the same root
// seed reproduce byte-identical output at any thread count.
//
// `progress` is called on the calling thread with the number of completed
// items, roughly a few times a second, and never concurrently with itself.
void parallelFor(uint64_t count, unsigned threads, const std::function<void(uint64_t, unsigned)>& body,
                 const std::function<void(uint64_t)>& progress = {});

}  // namespace fluxtools
