#pragma once

#include <cstdint>
#include <unordered_map>
#include "../core/types.hpp"
#include "../core/cache_line.hpp"
#include "../core/time_utils.hpp"

namespace quant::risk {

struct RiskLimits {
    int64_t max_order_notional{1'000'000 * core::Price::SCALE}; // Default $1M max per order
    double price_collar_pct{0.05};                              // 5% fat-finger deviation collar
    uint32_t max_orders_per_sec{5000};                          // Leaky bucket rate limit
    int64_t max_net_position{50000};                            // Max absolute net shares position
};

struct LeakyBucket {
    uint32_t tokens{0};
    uint64_t last_refill_ns{0};

    void refill(uint32_t rate_per_sec, uint64_t now_ns) noexcept {
        if (last_refill_ns == 0) {
            tokens = rate_per_sec;
            last_refill_ns = now_ns;
            return;
        }

        uint64_t elapsed_ns = now_ns - last_refill_ns;
        if (elapsed_ns >= 1'000'000'000ULL) {
            tokens = rate_per_sec;
            last_refill_ns = now_ns;
        } else {
            uint64_t new_tokens = (elapsed_ns * rate_per_sec) / 1'000'000'000ULL;
            if (new_tokens > 0) {
                tokens = std::min(rate_per_sec, tokens + static_cast<uint32_t>(new_tokens));
                last_refill_ns = now_ns;
            }
        }
    }

    bool consume() noexcept {
        if (tokens > 0) {
            --tokens;
            return true;
        }
        return false;
    }
};

class alignas(core::CACHELINE_SIZE) RiskEngine {
public:
    explicit RiskEngine(RiskLimits limits = RiskLimits{}) : limits_(limits) {}
    ~RiskEngine() = default;

    /**
     * Inline Pre-Trade Risk Check.
     * Evaluates in single-digit nanoseconds without locks.
     */
    [[nodiscard]] core::RejectReason check_order(
        core::ClientId client_id,
        core::Side side,
        core::Price price,
        core::Quantity qty,
        double current_mid_price,
        uint64_t now_ns = 0
    ) noexcept;

    /**
     * Update client position upon trade execution.
     */
    void on_fill(core::ClientId client_id, core::Side side, core::Quantity qty) noexcept;

    void set_limits(RiskLimits limits) noexcept { limits_ = limits; }
    [[nodiscard]] const RiskLimits& limits() const noexcept { return limits_; }

private:
    RiskLimits limits_;
    std::unordered_map<core::ClientId, LeakyBucket> rate_limiters_;
    std::unordered_map<core::ClientId, int64_t> net_positions_;
};

} // namespace quant::risk
