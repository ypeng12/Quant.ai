#include "../../include/order_book/order_book.hpp"
#include <cmath>

namespace quant::order_book {

bool OrderBook::add_resting_order(Order* order) noexcept {
    if (!order || order->leaves_qty == 0) return false;

    if (order->side == core::Side::BUY) {
        auto& level = bids_[order->price];
        level.price = order->price;
        level.append(order);
    } else if (order->side == core::Side::SELL) {
        auto& level = asks_[order->price];
        level.price = order->price;
        level.append(order);
    } else {
        return false;
    }

    orders_map_[order->order_id] = order;
    if (order->client_order_id != 0) {
        client_orders_map_[order->client_order_id] = order;
    }
    return true;
}

bool OrderBook::remove_order(Order* order) noexcept {
    if (!order) return false;

    if (order->side == core::Side::BUY) {
        auto it = bids_.find(order->price);
        if (it != bids_.end()) {
            it->second.remove(order);
            if (it->second.order_count == 0) {
                bids_.erase(it);
            }
        }
    } else if (order->side == core::Side::SELL) {
        auto it = asks_.find(order->price);
        if (it != asks_.end()) {
            it->second.remove(order);
            if (it->second.order_count == 0) {
                asks_.erase(it);
            }
        }
    }

    orders_map_.erase(order->order_id);
    if (order->client_order_id != 0) {
        client_orders_map_.erase(order->client_order_id);
    }
    return true;
}

bool OrderBook::reduce_order_qty(Order* order, core::Quantity fill_qty) noexcept {
    if (!order || fill_qty > order->leaves_qty) return false;

    if (order->side == core::Side::BUY) {
        auto it = bids_.find(order->price);
        if (it != bids_.end()) {
            it->second.total_volume -= fill_qty;
        }
    } else if (order->side == core::Side::SELL) {
        auto it = asks_.find(order->price);
        if (it != asks_.end()) {
            it->second.total_volume -= fill_qty;
        }
    }

    order->leaves_qty -= fill_qty;
    if (order->leaves_qty == 0) {
        remove_order(order);
    }
    return true;
}

std::optional<core::Price> OrderBook::best_bid() const noexcept {
    if (bids_.empty()) return std::nullopt;
    return bids_.begin()->first;
}

std::optional<core::Price> OrderBook::best_ask() const noexcept {
    if (asks_.empty()) return std::nullopt;
    return asks_.begin()->first;
}

double OrderBook::get_mid_price() const noexcept {
    auto bb = best_bid();
    auto ba = best_ask();
    if (bb && ba) {
        return 0.5 * (bb->to_double() + ba->to_double());
    }
    if (bb) return bb->to_double();
    if (ba) return ba->to_double();
    return 0.0;
}

double OrderBook::get_weighted_microprice() const noexcept {
    if (bids_.empty() || asks_.empty()) {
        return get_mid_price();
    }

    const auto& best_b = bids_.begin()->second;
    const auto& best_a = asks_.begin()->second;

    double bb_p = best_b.price.to_double();
    double ba_p = best_a.price.to_double();
    double bb_v = static_cast<double>(best_b.total_volume);
    double ba_v = static_cast<double>(best_a.total_volume);

    double total_v = bb_v + ba_v;
    if (total_v > 0.0) {
        return (bb_p * ba_v + ba_p * bb_v) / total_v;
    }
    return get_mid_price();
}

double OrderBook::get_book_imbalance() const noexcept {
    double bid_vol = 0.0;
    double ask_vol = 0.0;

    size_t count = 0;
    for (auto it = bids_.begin(); it != bids_.end() && count < 5; ++it, ++count) {
        bid_vol += it->second.total_volume;
    }

    count = 0;
    for (auto it = asks_.begin(); it != asks_.end() && count < 5; ++it, ++count) {
        ask_vol += it->second.total_volume;
    }

    double total = bid_vol + ask_vol;
    if (total > 0.0) {
        return (bid_vol - ask_vol) / total;
    }
    return 0.0;
}

void OrderBook::get_l2_snapshot(L2Snapshot& snapshot) const noexcept {
    snapshot.bid_count = 0;
    for (auto it = bids_.begin(); it != bids_.end() && snapshot.bid_count < L2Snapshot::MAX_DEPTH; ++it) {
        snapshot.bids[snapshot.bid_count] = L2Level{
            it->first.to_double(),
            static_cast<double>(it->second.total_volume),
            it->second.order_count
        };
        ++snapshot.bid_count;
    }

    snapshot.ask_count = 0;
    for (auto it = asks_.begin(); it != asks_.end() && snapshot.ask_count < L2Snapshot::MAX_DEPTH; ++it) {
        snapshot.asks[snapshot.ask_count] = L2Level{
            it->first.to_double(),
            static_cast<double>(it->second.total_volume),
            it->second.order_count
        };
        ++snapshot.ask_count;
    }
}

} // namespace quant::order_book
