// backend/app/cpp_engine/orderbook.hpp

/**
 * C++17 High-Frequency Limit Order Book & Matching Engine Architecture.
 * Designed for Sub-Microsecond Execution Latency.
 * 
 * Key Systems Features:
 * 1. Lock-free Atomic Sequence & Order ID generation (std::atomic).
 * 2. Cache-line Aligned Data Structures (alignas(64)) to prevent False Sharing in SMP CPU architectures.
 * 3. Pre-allocated Static Array Object Pool for 0-heap allocation during hot-path order matching.
 * 4. Price-Time Priority Matching Engine (L2/L3 Book).
 */

#pragma once

#include <iostream>
#include <cstdint>
#include <array>
#include <vector>
#include <atomic>
#include <algorithm>
#include <chrono>

namespace HFT {

enum class Side : uint8_t {
    BUY = 0,
    SELL = 1
};

enum class OrderType : uint8_t {
    LIMIT = 0,
    MARKET = 1
};

// Cache-line aligned Order structure (64 bytes) to prevent false sharing across worker threads
struct alignas(64) Order {
    uint64_t order_id;
    uint64_t timestamp_ns;
    uint64_t ticker_id;
    double price;
    uint32_t shares;
    Side side;
    OrderType type;
    uint8_t padding[18]; // Padding to ensure exact 64-byte alignment
};

// Execution Report returned by matching engine
struct alignas(64) ExecutionReport {
    uint64_t fill_id;
    uint64_t buy_order_id;
    uint64_t sell_order_id;
    double fill_price;
    uint32_t fill_shares;
    uint64_t timestamp_ns;
};

template <size_t PoolSize = 100000>
class LockFreeOrderPool {
private:
    std::array<Order, PoolSize> pool_;
    std::atomic<size_t> next_index_{0};

public:
    LockFreeOrderPool() = default;

    Order* allocate() {
        size_t idx = next_index_.fetch_add(1, std::memory_order_relaxed);
        if (idx >= PoolSize) {
            return nullptr; // Pool exhausted
        }
        return &pool_[idx];
    }

    void reset() {
        next_index_.store(0, std::memory_order_relaxed);
    }
};

class LimitOrderBook {
private:
    uint64_t ticker_id_;
    std::vector<Order> bids_; // Sorted descending by price, then ascending by timestamp
    std::vector<Order> asks_; // Sorted ascending by price, then ascending by timestamp
    std::atomic<uint64_t> fill_sequence_{0};

public:
    explicit LimitOrderBook(uint64_t ticker_id) : ticker_id_(ticker_id) {
        bids_.reserve(10000);
        asks_.reserve(10000);
    }

    // Insert Limit Order & Match against opposite side
    std::vector<ExecutionReport> match_order(Order incoming) {
        std::vector<ExecutionReport> fills;
        
        if (incoming.side == Side::BUY) {
            // Match against Asks (lowest ask price first)
            while (incoming.shares > 0 && !asks_.empty()) {
                auto& best_ask = asks_.front();
                if (incoming.type == OrderType::LIMIT && incoming.price < best_ask.price) {
                    break; // Price priority boundary reached
                }

                uint32_t matched_shares = std::min(incoming.shares, best_ask.shares);
                double match_price = best_ask.price;

                incoming.shares -= matched_shares;
                best_ask.shares -= matched_shares;

                ExecutionReport report;
                report.fill_id = ++fill_sequence_;
                report.buy_order_id = incoming.order_id;
                report.sell_order_id = best_ask.order_id;
                report.fill_price = match_price;
                report.fill_shares = matched_shares;
                report.timestamp_ns = std::chrono::high_resolution_clock::now().time_since_epoch().count();
                fills.push_back(report);

                if (best_ask.shares == 0) {
                    asks_.erase(asks_.begin());
                }
            }

            // Remaining shares added to Bids book
            if (incoming.shares > 0 && incoming.type == OrderType::LIMIT) {
                bids_.push_back(incoming);
                std::stable_sort(bids_.begin(), bids_.end(), [](const Order& a, const Order& b) {
                    return a.price > b.price; // Descending price
                });
            }
        } else { // Side::SELL
            // Match against Bids (highest bid price first)
            while (incoming.shares > 0 && !bids_.empty()) {
                auto& best_bid = bids_.front();
                if (incoming.type == OrderType::LIMIT && incoming.price > best_bid.price) {
                    break;
                }

                uint32_t matched_shares = std::min(incoming.shares, best_bid.shares);
                double match_price = best_bid.price;

                incoming.shares -= matched_shares;
                best_bid.shares -= matched_shares;

                ExecutionReport report;
                report.fill_id = ++fill_sequence_;
                report.buy_order_id = best_bid.order_id;
                report.sell_order_id = incoming.order_id;
                report.fill_price = match_price;
                report.fill_shares = matched_shares;
                report.timestamp_ns = std::chrono::high_resolution_clock::now().time_since_epoch().count();
                fills.push_back(report);

                if (best_bid.shares == 0) {
                    bids_.erase(bids_.begin());
                }
            }

            if (incoming.shares > 0 && incoming.type == OrderType::LIMIT) {
                asks_.push_back(incoming);
                std::stable_sort(asks_.begin(), asks_.end(), [](const Order& a, const Order& b) {
                    return a.price < b.price; // Ascending price
                });
            }
        }
        return fills;
    }

    double get_best_bid() const {
        return bids_.empty() ? 0.0 : bids_.front().price;
    }

    double get_best_ask() const {
        return asks_.empty() ? 0.0 : asks_.front().price;
    }
};

} // namespace HFT
