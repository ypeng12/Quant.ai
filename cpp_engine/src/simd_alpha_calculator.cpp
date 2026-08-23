// cpp_engine/src/simd_alpha_calculator.cpp
#include "../include/simd_alpha_calculator.hpp"
#include <algorithm>
#include <numeric>

std::vector<double> SIMDAlphaCalculator::calculate_ofi_vectorized(
    const std::vector<double>& bid_prices,
    const std::vector<double>& bid_sizes,
    const std::vector<double>& ask_prices,
    const std::vector<double>& ask_sizes
) {
    size_t n = bid_prices.size();
    std::vector<double> ofi(n, 0.0);
    if (n < 2) return ofi;

    for (size_t t = 1; t < n; ++t) {
        double delta_e_bid = 0.0;
        if (bid_prices[t] > bid_prices[t - 1]) {
            delta_e_bid = bid_sizes[t];
        } else if (bid_prices[t] == bid_prices[t - 1]) {
            delta_e_bid = bid_sizes[t] - bid_sizes[t - 1];
        } else {
            delta_e_bid = -bid_sizes[t - 1];
        }

        double delta_e_ask = 0.0;
        if (ask_prices[t] < ask_prices[t - 1]) {
            delta_e_ask = ask_sizes[t];
        } else if (ask_prices[t] == ask_prices[t - 1]) {
            delta_e_ask = ask_sizes[t] - ask_sizes[t - 1];
        } else {
            delta_e_ask = -ask_sizes[t - 1];
        }

        ofi[t] = delta_e_bid - delta_e_ask;
    }
    return ofi;
}

std::vector<double> SIMDAlphaCalculator::calculate_microprice_velocity(
    const std::vector<double>& mid_prices,
    const std::vector<double>& ofi_signals,
    size_t window
) {
    size_t n = mid_prices.size();
    std::vector<double> velocity(n, 0.0);
    if (n <= window) return velocity;

    for (size_t i = window; i < n; ++i) {
        double price_change = mid_prices[i] - mid_prices[i - window];
        double ofi_sum = 0.0;
        for (size_t j = i - window; j <= i; ++j) {
            ofi_sum += ofi_signals[j];
        }
        velocity[i] = price_change * 0.7 + (ofi_sum / window) * 0.3;
    }
    return velocity;
}

double SIMDAlphaCalculator::calculate_vpin_toxicity(
    const std::vector<double>& trade_volumes,
    const std::vector<double>& price_changes,
    size_t bucket_size
) {
    size_t n = trade_volumes.size();
    if (n == 0) return 0.0;

    double buy_vol = 0.0;
    double sell_vol = 0.0;
    double total_vol = 0.0;

    for (size_t i = 0; i < n; ++i) {
        double v = trade_volumes[i];
        total_vol += v;
        if (price_changes[i] >= 0) {
            buy_vol += v;
        } else {
            sell_vol += v;
        }
    }

    return total_vol > 0.0 ? std::abs(buy_vol - sell_vol) / total_vol : 0.0;
}
