#include "fast_alpha_engine.hpp"

namespace quant {

FastAlphaEngine::FastAlphaEngine(int window_size)
    : window_size_(window_size), cum_pv_(0.0), cum_vol_(0.0) {}

double FastAlphaEngine::calculate_micro_price(double bid_price, double ask_price, double bid_size, double ask_size) {
    double total_size = bid_size + ask_size;
    if (total_size <= 0.0) return (bid_price + ask_price) * 0.5;
    return (ask_size * bid_price + bid_size * ask_price) / total_size;
}

double FastAlphaEngine::calculate_obi(double bid_size, double ask_size) {
    double total_size = bid_size + ask_size;
    if (total_size <= 0.0) return 0.0;
    return (bid_size - ask_size) / total_size;
}

AlphaSignalPayload FastAlphaEngine::process_tick(const MarketTick& tick) {
    double micro_p = calculate_micro_price(tick.bid_price, tick.ask_price, tick.bid_size, tick.ask_size);
    double obi = calculate_obi(tick.bid_size, tick.ask_size);

    price_history_.push_back(tick.last_price);
    volume_history_.push_back(tick.last_volume);

    cum_pv_ += tick.last_price * tick.last_volume;
    cum_vol_ += tick.last_volume;

    double vwap = (cum_vol_ > 0.0) ? (cum_pv_ / cum_vol_) : tick.last_price;

    // Rolling volatility
    double vol = 0.0;
    if (price_history_.size() >= 5) {
        size_t n = std::min(price_history_.size(), static_cast<size_t>(window_size_));
        double sum = 0.0;
        for (size_t i = price_history_.size() - n; i < price_history_.size(); ++i) {
            sum += price_history_[i];
        }
        double mean = sum / n;
        double sq_sum = 0.0;
        for (size_t i = price_history_.size() - n; i < price_history_.size(); ++i) {
            sq_sum += (price_history_[i] - mean) * (price_history_[i] - mean);
        }
        vol = std::sqrt(sq_sum / (n - 1));
    }

    // Dynamic EMA calculation
    auto ema9_vec = fast_ema(price_history_, 9);
    auto ema21_vec = fast_ema(price_history_, 21);

    double ema9 = ema9_vec.back();
    double ema21 = ema21_vec.back();

    // Composite alpha score: OBI + VWAP Overextension + EMA Trend
    double signal_score = (obi * 0.4) + ((micro_p - vwap) / (vol + 1e-6) * 0.3) + ((ema9 - ema21) / (vol + 1e-6) * 0.3);

    return AlphaSignalPayload{
        micro_p,
        obi,
        vwap,
        vol,
        ema9,
        ema21,
        signal_score
    };
}

std::vector<double> FastAlphaEngine::fast_ema(const std::vector<double>& prices, int period) {
    std::vector<double> result(prices.size(), 0.0);
    if (prices.empty()) return result;

    double k = 2.0 / (period + 1);
    result[0] = prices[0];
    for (size_t i = 1; i < prices.size(); ++i) {
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k);
    }
    return result;
}

std::vector<double> FastAlphaEngine::fast_vwap(const std::vector<double>& prices, const std::vector<double>& volumes) {
    std::vector<double> result(prices.size(), 0.0);
    double cum_pv = 0.0;
    double cum_v = 0.0;

    for (size_t i = 0; i < prices.size(); ++i) {
        cum_pv += prices[i] * volumes[i];
        cum_v += volumes[i];
        result[i] = (cum_v > 0.0) ? (cum_pv / cum_v) : prices[i];
    }
    return result;
}

std::vector<double> FastAlphaEngine::fast_order_flow_imbalance(
    const std::vector<double>& bid_prices,
    const std::vector<double>& ask_prices,
    const std::vector<double>& bid_sizes,
    const std::vector<double>& ask_sizes
) {
    size_t n = std::min({bid_prices.size(), ask_prices.size(), bid_sizes.size(), ask_sizes.size()});
    std::vector<double> ofi(n, 0.0);

    for (size_t i = 1; i < n; ++i) {
        double delta_v_bid = 0.0;
        if (bid_prices[i] > bid_prices[i - 1]) {
            delta_v_bid = bid_sizes[i];
        } else if (bid_prices[i] == bid_prices[i - 1]) {
            delta_v_bid = bid_sizes[i] - bid_sizes[i - 1];
        }

        double delta_v_ask = 0.0;
        if (ask_prices[i] < ask_prices[i - 1]) {
            delta_v_ask = ask_sizes[i];
        } else if (ask_prices[i] == ask_prices[i - 1]) {
            delta_v_ask = ask_sizes[i] - ask_sizes[i - 1];
        }

        ofi[i] = delta_v_bid - delta_v_ask;
    }
    return ofi;
}

} // namespace quant
