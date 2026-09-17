#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace fluxtools {

// Summary of one metric over a run. Percentiles are what board_norms actually
// needs (spec 5.3 asks for distributions, not means), and they come from the
// sorted sample.
//
// Everything is computed after sorting, which matters for more than tidiness:
// floating-point addition is not associative, so summing in sorted order is
// what makes the mean and sd byte-identical regardless of how many threads
// produced the values.
struct Distribution {
    uint64_t count = 0;
    double mean = 0;
    double sd = 0;
    double min = 0, p10 = 0, p25 = 0, p50 = 0, p75 = 0, p90 = 0, max = 0;

    static Distribution from(std::vector<double> values);
};

// Tab-separated header and row matching Distribution's fields, so callers do
// not each invent a layout.
std::string distributionHeader(const char* leadingColumns);
std::string distributionRow(const std::string& leadingValues, const Distribution& dist);

}  // namespace fluxtools
