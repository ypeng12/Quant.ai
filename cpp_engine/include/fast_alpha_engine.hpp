#ifndef FAST_ALPHA_ENGINE_HPP
#define FAST_ALPHA_ENGINE_HPP

#include <vector>
#include <string>
#include <cmath>
#include <algorithm>
#include <numeric>

namespace quant {

struct MarketTick {
    double timestamp;
    double bid_price;
    double ask_price;
    double bid_size;
    double ask_size;
    double last_price;
    double last_volume;
};

struct AlphaSignalPayload {
    double micro_price;
    double order_book_imbalance;
    double vwap;
    double rolling_volatility;
    double ema_9;
    double ema_21;
    double signal_score;
};

class FastAlphaEngine {
public:
    FastAlphaEngine(int window_size = 20);

    // Compute Micro-Price: P_micro = (Ask_Size * Bid_Price + Bid_Size * Ask_Price) / (Bid_Size + Ask_Size)
    static double calculate_micro_price(double bid_price, double ask_price, double bid_size, double ask_size);

    // Compute Order Book Imbalance (OBI): OBI = (Bid_Size - Ask_Size) / (Bid_Size + Ask_Size)
    static double calculate_obi(double bid_size, double ask_size);

    // Process a stream of market ticks and compute real-time Alpha Signals
    AlphaSignalPayload process_tick(const MarketTick& tick);

    // Fast vector calculations for Python Pandas integration
    static std::vector<double> fast_ema(const std::vector<double>& prices, int period);
    static std::vector<double> fast_vwap(const std::vector<double>& prices, const std::vector<double>& volumes);
    static std::vector<double> fast_order_flow_imbalance(
        const std::vector<double>& bid_prices,
        const std::vector<double>& ask_prices,
        const std::vector<double>& bid_sizes,
        const std::vector<double>& ask_sizes
    );

private:
    int window_size_;
    std::vector<double> price_history_;
    std::vector<double> volume_history_;
    double cum_pv_;
    double cum_vol_;
};

} // namespace quant

#endif // FAST_ALPHA_ENGINE_HPP
