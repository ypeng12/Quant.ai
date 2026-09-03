#pragma once

#include <cstdint>
#include <vector>
#include <map>
#include <functional>
#include <optional>
#include "../core/types.hpp"
#include "../protocol/binary_protocol.hpp"

namespace quant::market_data {

struct SequenceGap {
    uint64_t from_seq;
    uint64_t to_seq;
    uint64_t detected_at_ns;
};

class GapRecoveryTracker {
public:
    using GapCallback = std::function<void(const SequenceGap&)>;
    using InOrderTickCallback = std::function<void(const protocol::MarketDataTickPayload&, uint64_t seq, uint64_t ts)>;

    static constexpr size_t HISTORY_CAPACITY = 65536;

    explicit GapRecoveryTracker(GapCallback on_gap = nullptr, InOrderTickCallback on_tick = nullptr);

    /**
     * Process an incoming market data tick packet.
     * Detects gaps, buffers out-of-order packets, and releases sequential in-order stream.
     */
    void on_packet_received(
        uint64_t seq_num,
        uint64_t timestamp_ns,
        const protocol::MarketDataTickPayload& payload
    );

    /**
     * Process retransmitted recovered packets.
     */
    void on_gap_packet_recovered(
        uint64_t seq_num,
        uint64_t timestamp_ns,
        const protocol::MarketDataTickPayload& payload
    );

    /**
     * Store sent packet into historical ring buffer for serving retransmission requests.
     */
    void store_historical_packet(uint64_t seq_num, const protocol::MarketDataTickPayload& payload);

    /**
     * Look up historical packet by sequence number for retransmission serving.
     */
    [[nodiscard]] std::optional<protocol::MarketDataTickPayload> get_historical_packet(uint64_t seq_num) const;

    [[nodiscard]] uint64_t expected_seq() const noexcept { return expected_seq_; }
    [[nodiscard]] uint64_t total_gaps_detected() const noexcept { return total_gaps_detected_; }
    [[nodiscard]] uint64_t total_packets_processed() const noexcept { return total_packets_processed_; }

    void reset(uint64_t initial_seq = 1) noexcept;

private:
    void drain_buffered_packets();

    uint64_t expected_seq_{1};
    uint64_t total_gaps_detected_{0};
    uint64_t total_packets_processed_{0};

    GapCallback on_gap_;
    InOrderTickCallback on_tick_;

    // Out-of-order reassembly buffer
    struct BufferedPacket {
        uint64_t seq_num;
        uint64_t timestamp_ns;
        protocol::MarketDataTickPayload payload;
    };
    std::map<uint64_t, BufferedPacket> pending_buffer_;

    // Historical cache for serving retransmissions
    struct HistoricalSlot {
        uint64_t seq_num{0};
        protocol::MarketDataTickPayload payload;
    };
    std::vector<HistoricalSlot> history_cache_;
};

} // namespace quant::market_data
