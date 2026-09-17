#include "fluxcore.h"

#include "dawg.h"

int flux_dawg_load(const uint8_t* data, size_t size, FluxDawgHandle* outHandle) {
    if (outHandle == nullptr) return 0;
    auto* dawg = new fluxcore::Dawg();
    if (!dawg->loadFromMemory(data, size)) {
        delete dawg;
        outHandle->impl = nullptr;
        return 0;
    }
    outHandle->impl = dawg;
    return 1;
}

void flux_dawg_destroy(FluxDawgHandle* handle) {
    if (handle == nullptr || handle->impl == nullptr) return;
    delete static_cast<fluxcore::Dawg*>(handle->impl);
    handle->impl = nullptr;
}

uint32_t flux_dawg_word_count(const FluxDawgHandle* handle) {
    if (handle == nullptr || handle->impl == nullptr) return 0;
    return static_cast<const fluxcore::Dawg*>(handle->impl)->wordCount();
}

int flux_dawg_find_word_id(const FluxDawgHandle* handle, const char* word, size_t len, uint32_t* outId) {
    if (handle == nullptr || handle->impl == nullptr) return 0;
    const auto* dawg = static_cast<const fluxcore::Dawg*>(handle->impl);
    return dawg->findWordId(word, len, outId) ? 1 : 0;
}
