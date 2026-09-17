#include "thread_pool.h"

#include <atomic>
#include <chrono>
#include <thread>
#include <vector>

namespace fluxtools {

void parallelFor(uint64_t count, unsigned threads, const std::function<void(uint64_t, unsigned)>& body,
                 const std::function<void(uint64_t)>& progress) {
    if (count == 0) return;
    if (threads == 0) threads = 1;

    std::atomic<uint64_t> next{0};
    std::atomic<uint64_t> done{0};

    std::vector<std::thread> workers;
    workers.reserve(threads);
    for (unsigned t = 0; t < threads; ++t) {
        workers.emplace_back([&, t]() {
            for (;;) {
                const uint64_t index = next.fetch_add(1, std::memory_order_relaxed);
                if (index >= count) return;
                body(index, t);
                done.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }

    if (progress) {
        for (;;) {
            const uint64_t completed = done.load(std::memory_order_relaxed);
            progress(completed);
            if (completed >= count) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(250));
        }
    }

    for (std::thread& worker : workers) worker.join();
    if (progress) progress(count);
}

}  // namespace fluxtools
