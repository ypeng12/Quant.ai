#pragma once

#include <cstdint>
#include <array>
#include <map>
#include <unordered_map>
#include <vector>
#include <functional>
#include <optional>
#include "../core/types.hpp"
#include "../core/cache_line.hpp"
#include "../core/object_pool.hpp"

namespace quant::order_book {

// Intrusive doubly linked list node for zero-allocation order tracking
struct Order {
    core::OrderId order_id{0};
    core::ClientId client_id{0};
    core::ClientOrderId client_order_id{0};
    core::Symbol symbol;
    core::Price price;
    core::Quantity qty{0};
    core::Quantity leaves_qty{0};
    core::Side side{core::Side::UNKNOWN};
    core::OrderType order_type{core::OrderType::LIMIT};
    core::TimestampNs timestamp_ns{0};

    Order* prev{nullptr};
    Order* next{nullptr};
};

struct alignas(core::CACHELINE_SIZE) PriceLevel {
    core::Price price;
    core::Quantity total_volume{0};
    uint32_t order_count{0};
    Order* head{nullptr};
    Order* tail{nullptr};

    void append(Order* order) noexcept {
        order->next = nullptr;
        order->prev = tail;
        if (tail) {
            tail->next = order;
        } else {
            head = order;
        }
        tail = order;
        total_volume += order->leaves_qty;
        ++order_count;
    }

    void remove(Order* order) noexcept {
        if (order->prev) {
            order->prev->next = order->next;
        } else {
            head = order->next;
        }
        if (order->next) {
            order->next->prev = order->prev;
        } else {
            tail = order->prev;
        }
        total_volume -= order->leaves_qty;
        --order_count;
    }
};

struct L2Level {
    double price{0.0};
    double volume{0.0};
    uint32_t count{0};
};

struct alignas(core::CACHELINE_SIZE) L2Snapshot {
    static constexpr size_t MAX_DEPTH = 10;
    std::array<L2Level, MAX_DEPTH> bids;
    std::array<L2Level, MAX_DEPTH> asks;
    size_t bid_count{0};
    size_t ask_count{0};
    core::TimestampNs timestamp_ns{0};
};

class alignas(core::CACHELINE_SIZE) OrderBook {
public:
    static constexpr size_t MAX_ORDERS = 131072; // 128k orders in memory pool

    explicit OrderBook(core::Symbol symbol) : symbol_(symbol), order_pool_() {}

    ~OrderBook() = default;

    OrderBook(const OrderBook&) = delete;
    OrderBook& operator=(const OrderBook&) = delete;

    // Direct O(1) order lookup
    [[nodiscard]] Order* find_order(core::OrderId order_id) noexcept {
        auto it = orders_map_.find(order_id);
        return it != orders_map_.end() ? it->second : nullptr;
    }

    [[nodiscard]] Order* find_order_by_client_id(core::ClientOrderId client_order_id) noexcept {
        auto it = client_orders_map_.find(client_order_id);
        return it != client_orders_map_.end() ? it->second : nullptr;
    }

    // Allocate order from zero-allocation pool
    template <typename... Args>
    [[nodiscard]] Order* allocate_order(Args&&... args) {
        return order_pool_.allocate(std::forward<Args>(args)...);
    }

    void free_order(Order* order) noexcept {
        order_pool_.deallocate(order);
    }

    // Add resting limit order to the book
    bool add_resting_order(Order* order) noexcept;

    // Remove / Cancel resting order
    bool remove_order(Order* order) noexcept;

    // Reduce order quantity (partial fill or modify)
    bool reduce_order_qty(Order* order, core::Quantity fill_qty) noexcept;

    // Best bid / ask price
    [[nodiscard]] std::optional<core::Price> best_bid() const noexcept;
    [[nodiscard]] std::optional<core::Price> best_ask() const noexcept;

    // Market metrics
    [[nodiscard]] double get_mid_price() const noexcept;
    [[nodiscard]] double get_weighted_microprice() const noexcept;
    [[nodiscard]] double get_book_imbalance() const noexcept;

    // Extract L2 Top of Book snapshot
    void get_l2_snapshot(L2Snapshot& snapshot) const noexcept;

    [[nodiscard]] core::Symbol symbol() const noexcept { return symbol_; }
    [[nodiscard]] size_t order_count() const noexcept { return orders_map_.size(); }

    // Bid and Ask books
    // Bids sorted descending (highest price first), Asks sorted ascending (lowest price first)
    auto& bids() noexcept { return bids_; }
    auto& asks() noexcept { return asks_; }
    const auto& bids() const noexcept { return bids_; }
    const auto& asks() const noexcept { return asks_; }

private:
    core::Symbol symbol_;
    core::ObjectPool<Order, MAX_ORDERS> order_pool_;
    std::unordered_map<core::OrderId, Order*> orders_map_;
    std::unordered_map<core::ClientOrderId, Order*> client_orders_map_;

    // Sorted price levels
    std::map<core::Price, PriceLevel, std::greater<core::Price>> bids_;
    std::map<core::Price, PriceLevel, std::less<core::Price>> asks_;
};

} // namespace quant::order_book
