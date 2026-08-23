// cpp_engine/include/orderbook.hpp
#ifndef ORDERBOOK_HPP
#define ORDERBOOK_HPP

#include <iostream>
#include <vector>
#include <array>
#include <algorithm>
#include <cstdint>
#include <cmath>

// 64-byte Cache-line alignment to prevent false sharing in HFT multi-threading
struct alignas(64) OrderBookLevel {
    double price;
    double volume;
    uint32_t order_count;
};

class alignas(64) FastL2OrderBook {
private:
    static constexpr size_t MAX_LEVELS = 10;
    std::array<OrderBookLevel, MAX_LEVELS> bids;
    std::array<OrderBookLevel, MAX_LEVELS> asks;
    size_t bid_depth;
    size_t ask_depth;
    uint64_t timestamp_ns;

public:
    FastL2OrderBook() : bid_depth(0), ask_depth(0), timestamp_ns(0) {
        bids.fill({0.0, 0.0, 0});
        asks.fill({0.0, 0.0, 0});
    }

    void update_bid(size_t level, double price, double volume, uint32_t count = 1) {
        if (level < MAX_LEVELS) {
            bids[level] = {price, volume, count};
            if (level >= bid_depth && volume > 0) {
                bid_depth = level + 1;
            }
        }
    }

    void update_ask(size_t level, double price, double volume, uint32_t count = 1) {
        if (level < MAX_LEVELS) {
            asks[level] = {price, volume, count};
            if (level >= ask_depth && volume > 0) {
                ask_depth = level + 1;
            }
        }
    }

    double get_best_bid() const {
        return bid_depth > 0 ? bids[0].price : 0.0;
    }

    double get_best_ask() const {
        return ask_depth > 0 ? asks[0].price : 0.0;
    }

    double get_mid_price() const {
        double bb = get_best_bid();
        double ba = get_best_ask();
        return (bb > 0.0 && ba > 0.0) ? 0.5 * (bb + ba) : 0.0;
    }

    double get_weighted_microprice() const {
        double bb = get_best_bid();
        double ba = get_best_ask();
        double bv = bids[0].volume;
        double av = asks[0].volume;
        double total_vol = bv + av;
        return total_vol > 0.0 ? (bb * av + ba * bv) / total_vol : get_mid_price();
    }

    double calculate_book_imbalance() const {
        double total_bid_vol = 0.0;
        double total_ask_vol = 0.0;
        for (size_t i = 0; i < std::min(bid_depth, size_t(5)); ++i) {
            total_bid_vol += bids[i].volume;
        }
        for (size_t i = 0; i < std::min(ask_depth, size_t(5)); ++i) {
            total_ask_vol += asks[i].volume;
        }
        double total = total_bid_vol + total_ask_vol;
        return total > 0.0 ? (total_bid_vol - total_ask_vol) / total : 0.0;
    }
};

#endif // ORDERBOOK_HPP
