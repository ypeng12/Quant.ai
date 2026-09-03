#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <vector>
#include "../core/types.hpp"
#include "../protocol/binary_protocol.hpp"
#include "order_book.hpp"

namespace quant::order_book {

class alignas(core::CACHELINE_SIZE) MatchingEngine {
public:
    using ExecutionCallback = std::function<void(const protocol::ExecutionReportPayload&)>;

    explicit MatchingEngine(core::Symbol symbol, ExecutionCallback on_exec = nullptr);
    ~MatchingEngine() = default;

    MatchingEngine(const MatchingEngine&) = delete;
    MatchingEngine& operator=(const MatchingEngine&) = delete;

    void set_execution_callback(ExecutionCallback cb) noexcept {
        on_exec_ = std::move(cb);
    }

    /**
     * Submit and match a new incoming order.
     */
    void process_new_order(
        core::ClientId client_id,
        core::ClientOrderId client_order_id,
        core::Side side,
        core::OrderType type,
        core::Price price,
        core::Quantity qty,
        core::TimestampNs timestamp_ns
    );

    /**
     * Cancel an existing order by client order ID or engine order ID.
     */
    bool cancel_order(
        core::ClientId client_id,
        core::ClientOrderId client_order_id,
        core::OrderId engine_order_id,
        core::TimestampNs timestamp_ns
    );

    /**
     * Invariant check:
     * - Best bid price must be strictly strictly lower than best ask price (No crossed/locked book).
     */
    [[nodiscard]] bool check_invariants() const noexcept;

    [[nodiscard]] const OrderBook& book() const noexcept { return book_; }
    [[nodiscard]] OrderBook& book() noexcept { return book_; }

    [[nodiscard]] uint64_t total_trades() const noexcept { return total_trades_; }
    [[nodiscard]] uint64_t total_volume() const noexcept { return total_volume_; }

private:
    void emit_report(
        core::ClientId client_id,
        core::ClientOrderId client_order_id,
        core::OrderId engine_order_id,
        core::ExecType exec_type,
        core::Price fill_price,
        core::Quantity fill_qty,
        core::Quantity leaves_qty,
        core::RejectReason reason
    ) noexcept;

    OrderBook book_;
    ExecutionCallback on_exec_;
    core::OrderId next_engine_order_id_{1};
    uint64_t next_exec_id_{1};
    uint64_t total_trades_{0};
    uint64_t total_volume_{0};
};

} // namespace quant::order_book
