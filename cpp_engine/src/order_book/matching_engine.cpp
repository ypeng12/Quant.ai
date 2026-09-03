#include "../../include/order_book/matching_engine.hpp"
#include <algorithm>

namespace quant::order_book {

MatchingEngine::MatchingEngine(core::Symbol symbol, ExecutionCallback on_exec)
    : book_(symbol), on_exec_(std::move(on_exec)) {}

void MatchingEngine::emit_report(
    core::ClientId client_id,
    core::ClientOrderId client_order_id,
    core::OrderId engine_order_id,
    core::ExecType exec_type,
    core::Price fill_price,
    core::Quantity fill_qty,
    core::Quantity leaves_qty,
    core::RejectReason reason
) noexcept {
    if (!on_exec_) return;

    protocol::ExecutionReportPayload report;
    report.client_id = client_id;
    report.client_order_id = client_order_id;
    report.engine_order_id = engine_order_id;
    report.exec_id = next_exec_id_++;
    report.exec_type = static_cast<uint8_t>(exec_type);
    report.fill_price_raw = fill_price.raw();
    report.fill_qty = fill_qty;
    report.leaves_qty = leaves_qty;
    report.reject_reason = static_cast<uint8_t>(reason);

    on_exec_(report);
}

void MatchingEngine::process_new_order(
    core::ClientId client_id,
    core::ClientOrderId client_order_id,
    core::Side side,
    core::OrderType type,
    core::Price price,
    core::Quantity qty,
    core::TimestampNs timestamp_ns
) {
    if (qty == 0) {
        emit_report(client_id, client_order_id, 0, core::ExecType::REJECTED,
                    price, 0, 0, core::RejectReason::INVALID_QUANTITY);
        return;
    }

    if (type == core::OrderType::LIMIT && price.raw() <= 0) {
        emit_report(client_id, client_order_id, 0, core::ExecType::REJECTED,
                    price, 0, 0, core::RejectReason::INVALID_PRICE);
        return;
    }

    core::OrderId engine_order_id = next_engine_order_id_++;
    core::Quantity remaining_qty = qty;

    // Matching logic
    if (side == core::Side::BUY) {
        // Match against resting ASKS (lowest price first)
        while (remaining_qty > 0 && !book_.asks().empty()) {
            auto best_ask_it = book_.asks().begin();
            core::Price best_ask_price = best_ask_it->first;

            if (type == core::OrderType::LIMIT && price < best_ask_price) {
                break; // No more matching asks at or below limit buy price
            }

            Order* resting = best_ask_it->second.head;
            if (!resting) {
                book_.asks().erase(best_ask_it);
                continue;
            }

            core::Quantity match_qty = std::min(remaining_qty, resting->leaves_qty);
            remaining_qty -= match_qty;
            resting->leaves_qty -= match_qty;
            best_ask_it->second.total_volume -= match_qty;
            total_volume_ += match_qty;
            ++total_trades_;

            bool maker_filled = (resting->leaves_qty == 0);
            core::Quantity resting_leaves = resting->leaves_qty;
            core::OrderId resting_order_id = resting->order_id;
            core::ClientId resting_client_id = resting->client_id;
            core::ClientOrderId resting_client_order_id = resting->client_order_id;

            if (maker_filled) {
                book_.remove_order(resting);
                book_.free_order(resting);
            }

            // Emit executions for resting maker
            emit_report(
                resting_client_id,
                resting_client_order_id,
                resting_order_id,
                maker_filled ? core::ExecType::FILL : core::ExecType::PARTIAL_FILL,
                best_ask_price,
                match_qty,
                resting_leaves,
                core::RejectReason::NONE
            );

            // Emit execution for incoming taker
            emit_report(
                client_id,
                client_order_id,
                engine_order_id,
                remaining_qty == 0 ? core::ExecType::FILL : core::ExecType::PARTIAL_FILL,
                best_ask_price,
                match_qty,
                remaining_qty,
                core::RejectReason::NONE
            );
        }

        // Post-match leaves handling
        if (remaining_qty > 0) {
            if (type == core::OrderType::LIMIT) {
                Order* order = book_.allocate_order();
                if (order) {
                    order->order_id = engine_order_id;
                    order->client_id = client_id;
                    order->client_order_id = client_order_id;
                    order->symbol = book_.symbol();
                    order->price = price;
                    order->qty = qty;
                    order->leaves_qty = remaining_qty;
                    order->side = side;
                    order->order_type = type;
                    order->timestamp_ns = timestamp_ns;

                    book_.add_resting_order(order);
                    emit_report(client_id, client_order_id, engine_order_id,
                                core::ExecType::NEW, price, 0, remaining_qty, core::RejectReason::NONE);
                }
            } else if (type == core::OrderType::IOC || type == core::OrderType::MARKET) {
                emit_report(client_id, client_order_id, engine_order_id,
                            core::ExecType::CANCELED, price, 0, remaining_qty, core::RejectReason::NONE);
            }
        }
    } else if (side == core::Side::SELL) {
        // Match against resting BIDS (highest price first)
        while (remaining_qty > 0 && !book_.bids().empty()) {
            auto best_bid_it = book_.bids().begin();
            core::Price best_bid_price = best_bid_it->first;

            if (type == core::OrderType::LIMIT && price > best_bid_price) {
                break; // No more matching bids at or above limit sell price
            }

            Order* resting = best_bid_it->second.head;
            if (!resting) {
                book_.bids().erase(best_bid_it);
                continue;
            }

            core::Quantity match_qty = std::min(remaining_qty, resting->leaves_qty);
            remaining_qty -= match_qty;
            resting->leaves_qty -= match_qty;
            best_bid_it->second.total_volume -= match_qty;
            total_volume_ += match_qty;
            ++total_trades_;

            bool maker_filled = (resting->leaves_qty == 0);
            core::Quantity resting_leaves = resting->leaves_qty;
            core::OrderId resting_order_id = resting->order_id;
            core::ClientId resting_client_id = resting->client_id;
            core::ClientOrderId resting_client_order_id = resting->client_order_id;

            if (maker_filled) {
                book_.remove_order(resting);
                book_.free_order(resting);
            }

            // Emit executions for resting maker
            emit_report(
                resting_client_id,
                resting_client_order_id,
                resting_order_id,
                maker_filled ? core::ExecType::FILL : core::ExecType::PARTIAL_FILL,
                best_bid_price,
                match_qty,
                resting_leaves,
                core::RejectReason::NONE
            );

            // Emit execution for incoming taker
            emit_report(
                client_id,
                client_order_id,
                engine_order_id,
                remaining_qty == 0 ? core::ExecType::FILL : core::ExecType::PARTIAL_FILL,
                best_bid_price,
                match_qty,
                remaining_qty,
                core::RejectReason::NONE
            );
        }

        // Post-match leaves handling
        if (remaining_qty > 0) {
            if (type == core::OrderType::LIMIT) {
                Order* order = book_.allocate_order();
                if (order) {
                    order->order_id = engine_order_id;
                    order->client_id = client_id;
                    order->client_order_id = client_order_id;
                    order->symbol = book_.symbol();
                    order->price = price;
                    order->qty = qty;
                    order->leaves_qty = remaining_qty;
                    order->side = side;
                    order->order_type = type;
                    order->timestamp_ns = timestamp_ns;

                    book_.add_resting_order(order);
                    emit_report(client_id, client_order_id, engine_order_id,
                                core::ExecType::NEW, price, 0, remaining_qty, core::RejectReason::NONE);
                }
            } else if (type == core::OrderType::IOC || type == core::OrderType::MARKET) {
                emit_report(client_id, client_order_id, engine_order_id,
                            core::ExecType::CANCELED, price, 0, remaining_qty, core::RejectReason::NONE);
            }
        }
    }
}

bool MatchingEngine::cancel_order(
    core::ClientId client_id,
    core::ClientOrderId client_order_id,
    core::OrderId engine_order_id,
    core::TimestampNs timestamp_ns
) {
    (void)timestamp_ns;
    Order* order = nullptr;
    if (engine_order_id != 0) {
        order = book_.find_order(engine_order_id);
    }
    if (!order && client_order_id != 0) {
        order = book_.find_order_by_client_id(client_order_id);
    }

    if (!order) {
        emit_report(client_id, client_order_id, engine_order_id,
                    core::ExecType::REJECTED, core::Price(), 0, 0,
                    core::RejectReason::ORDER_NOT_FOUND);
        return false;
    }

    core::Quantity leaves = order->leaves_qty;
    book_.remove_order(order);
    emit_report(client_id, client_order_id, order->order_id,
                core::ExecType::CANCELED, order->price, 0, leaves,
                core::RejectReason::NONE);
    book_.free_order(order);
    return true;
}

bool MatchingEngine::check_invariants() const noexcept {
    auto bb = book_.best_bid();
    auto ba = book_.best_ask();
    if (bb && ba) {
        return *bb < *ba; // Crossed or locked book invariant check
    }
    return true;
}

} // namespace quant::order_book
