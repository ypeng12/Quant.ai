#pragma once

#include <cstdint>
#include <vector>
#include <string>
#include <unordered_map>
#include <functional>
#include <memory>
#include <span>
#include "../core/types.hpp"
#include "../core/time_utils.hpp"
#include "../protocol/itch50_protocol.hpp"
#include "../protocol/ouch_protocol.hpp"
#include "../order_book/matching_engine.hpp"

namespace quant::gateway {

using namespace protocol::itch50;
using namespace protocol::ouch;

class alignas(core::CACHELINE_SIZE) ITCHOUCHExchangeSimulator {
public:
    using ITCHBroadcastCallback = std::function<void(std::span<const uint8_t> itch_msg)>;

    explicit ITCHOUCHExchangeSimulator(core::Symbol symbol, ITCHBroadcastCallback on_itch = nullptr);

    ~ITCHOUCHExchangeSimulator() = default;

    /**
     * Submit an OUCH Enter Order ('O') message.
     * Returns Outbound OUCH message bytes (Accepted / Executed / Rejected).
     */
    std::vector<uint8_t> process_enter_order(const EnterOrderMsg& enter_msg);

    /**
     * Submit an OUCH Cancel Order ('X') message.
     */
    std::vector<uint8_t> process_cancel_order(const CancelOrderMsg& cancel_msg);

    /**
     * Submit an OUCH Replace Order ('U') message.
     */
    std::vector<uint8_t> process_replace_order(const ReplaceOrderMsg& replace_msg);

    /**
     * Generate an L2/L3 Order Book Snapshot message for clients syncing after disconnect.
     */
    std::vector<uint8_t> generate_snapshot_packet();

    [[nodiscard]] const std::vector<std::vector<uint8_t>>& emitted_itch_feed() const noexcept {
        return emitted_itch_feed_;
    }

    [[nodiscard]] order_book::MatchingEngine& matching_engine() noexcept { return matching_engine_; }
    [[nodiscard]] uint64_t total_orders_received() const noexcept { return total_orders_; }

private:
    void broadcast_itch(const void* data, size_t len);

    core::Symbol symbol_;
    ITCHBroadcastCallback on_itch_;
    order_book::MatchingEngine matching_engine_;

    uint64_t next_order_ref_num_{1000001};
    uint64_t next_match_num_{1};
    uint64_t total_orders_{0};

    // Mapping from OUCH OrderToken string to internal engine Order ID & state
    struct TokenMeta {
        uint64_t engine_order_id{0};
        uint64_t order_ref_num{0};
        char buy_sell{'B'};
        uint32_t leaves_qty{0};
        uint32_t price{0};
    };
    std::unordered_map<std::string, TokenMeta> token_to_meta_;
    std::unordered_map<uint64_t, std::string> ref_to_token_;

    std::vector<std::vector<uint8_t>> emitted_itch_feed_;
};

} // namespace quant::gateway
