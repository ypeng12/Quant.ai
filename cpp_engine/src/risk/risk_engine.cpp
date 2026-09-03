#include "../../include/risk/risk_engine.hpp"
#include <cmath>

namespace quant::risk {

core::RejectReason RiskEngine::check_order(
    core::ClientId client_id,
    core::Side side,
    core::Price price,
    core::Quantity qty,
    double current_mid_price,
    uint64_t now_ns
) noexcept {
    if (now_ns == 0) {
        now_ns = core::TimeUtils::now_ns();
    }

    // 1. Quantity check
    if (qty == 0) {
        return core::RejectReason::INVALID_QUANTITY;
    }

    // 2. Notional value check (Price * Qty)
    int64_t notional = price.raw() * qty;
    if (notional > limits_.max_order_notional) {
        return core::RejectReason::RISK_NOTIONAL_EXCEEDED;
    }

    // 3. Fat-finger Price Collar check (against book mid-price)
    if (current_mid_price > 0.0 && price.is_positive()) {
        double order_p = price.to_double();
        double deviation = std::abs(order_p - current_mid_price) / current_mid_price;
        if (deviation > limits_.price_collar_pct) {
            return core::RejectReason::RISK_PRICE_COLLAR_VIOLATED;
        }
    }

    // 4. Leaky Bucket Rate Limiter check
    auto& bucket = rate_limiters_[client_id];
    bucket.refill(limits_.max_orders_per_sec, now_ns);
    if (!bucket.consume()) {
        return core::RejectReason::RISK_RATE_LIMIT_EXCEEDED;
    }

    // 5. Position Limit check
    int64_t current_pos = net_positions_[client_id];
    int64_t delta = (side == core::Side::BUY) ? static_cast<int64_t>(qty) : -static_cast<int64_t>(qty);
    int64_t projected_pos = current_pos + delta;
    if (std::abs(projected_pos) > limits_.max_net_position) {
        return core::RejectReason::RISK_POSITION_LIMIT_EXCEEDED;
    }

    return core::RejectReason::NONE;
}

void RiskEngine::on_fill(core::ClientId client_id, core::Side side, core::Quantity qty) noexcept {
    int64_t delta = (side == core::Side::BUY) ? static_cast<int64_t>(qty) : -static_cast<int64_t>(qty);
    net_positions_[client_id] += delta;
}

} // namespace quant::risk
