#include "stats.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace fluxtools {
namespace {

double percentile(const std::vector<double>& sorted, double fraction) {
    if (sorted.empty()) return 0.0;
    const size_t index = static_cast<size_t>(fraction * static_cast<double>(sorted.size() - 1));
    return sorted[std::min(index, sorted.size() - 1)];
}

}  // namespace

Distribution Distribution::from(std::vector<double> values) {
    Distribution dist;
    if (values.empty()) return dist;
    std::sort(values.begin(), values.end());

    dist.count = values.size();
    double sum = 0;
    for (double v : values) sum += v;
    dist.mean = sum / static_cast<double>(values.size());

    double sumSquares = 0;
    for (double v : values) {
        const double delta = v - dist.mean;
        sumSquares += delta * delta;
    }
    dist.sd = std::sqrt(sumSquares / static_cast<double>(values.size()));

    dist.min = values.front();
    dist.max = values.back();
    dist.p10 = percentile(values, 0.10);
    dist.p25 = percentile(values, 0.25);
    dist.p50 = percentile(values, 0.50);
    dist.p75 = percentile(values, 0.75);
    dist.p90 = percentile(values, 0.90);
    return dist;
}

std::string distributionHeader(const char* leadingColumns) {
    return std::string(leadingColumns) + "\tboards\tmean\tsd\tmin\tp10\tp25\tp50\tp75\tp90\tmax";
}

std::string distributionRow(const std::string& leadingValues, const Distribution& dist) {
    char buf[512];
    std::snprintf(buf, sizeof(buf), "\t%llu\t%.2f\t%.2f\t%.0f\t%.0f\t%.0f\t%.0f\t%.0f\t%.0f\t%.0f",
                  static_cast<unsigned long long>(dist.count), dist.mean, dist.sd, dist.min,
                  dist.p10, dist.p25, dist.p50, dist.p75, dist.p90, dist.max);
    return leadingValues + buf;
}

}  // namespace fluxtools
