// cpp_engine/include/simd_alpha_calculator.hpp
#ifndef SIMD_ALPHA_CALCULATOR_HPP
#define SIMD_ALPHA_CALCULATOR_HPP

#include <vector>
#include <cstddef>
#include <cmath>

class SIMDAlphaCalculator {
public:
    // Fast vector calculation of Order Flow Imbalance (OFI)
    static std::vector<double> calculate_ofi_vectorized(
        const std::vector<double>& bid_prices,
        const std::vector<double>& bid_sizes,
        const std::vector<double>& ask_prices,
        const std::vector<double>& ask_sizes
    );

    // Fast vector calculation of MicroPrice Drift Velocity
    static std::vector<double> calculate_microprice_velocity(
        const std::vector<double>& mid_prices,
        const std::vector<double>& ofi_signals,
        size_t window = 5
    );

    // Calculation of Volume-Synchronized Probability of Toxicity (VPIN)
    static double calculate_vpin_toxicity(
        const std::vector<double>& trade_volumes,
        const std::vector<double>& price_changes,
        size_t bucket_size = 1000
    );
};

#endif // SIMD_ALPHA_CALCULATOR_HPP
