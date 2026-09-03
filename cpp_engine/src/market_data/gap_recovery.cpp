#include "../../include/market_data/gap_recovery.hpp"
#include "../../include/core/time_utils.hpp"

namespace quant::market_data {

GapRecoveryTracker::GapRecoveryTracker(GapCallback on_gap, InOrderTickCallback on_tick)
    : on_gap_(std::move(on_gap)), on_tick_(std::move(on_tick)) {
    history_cache_.resize(HISTORY_CAPACITY);
}

void GapRecoveryTracker::reset(uint64_t initial_seq) noexcept {
    expected_seq_ = initial_seq;
    total_gaps_detected_ = 0;
    total_packets_processed_ = 0;
    pending_buffer_.clear();
}

void GapRecoveryTracker::on_packet_received(
    uint64_t seq_num,
    uint64_t timestamp_ns,
    const protocol::MarketDataTickPayload& payload
) {
    if (seq_num < expected_seq_) {
        // Duplicate or stale packet, ignore
        return;
    }

    if (seq_num == expected_seq_) {
        // In-order packet
        ++expected_seq_;
        ++total_packets_processed_;
        if (on_tick_) {
            on_tick_(payload, seq_num, timestamp_ns);
        }
        drain_buffered_packets();
    } else {
        // Sequence gap detected: seq_num > expected_seq_
        ++total_gaps_detected_;
        SequenceGap gap{
            expected_seq_,
            seq_num - 1,
            core::TimeUtils::now_ns()
        };

        if (on_gap_) {
            on_gap_(gap);
        }

        // Buffer the ahead-of-time packet
        pending_buffer_[seq_num] = BufferedPacket{seq_num, timestamp_ns, payload};
    }
}

void GapRecoveryTracker::on_gap_packet_recovered(
    uint64_t seq_num,
    uint64_t timestamp_ns,
    const protocol::MarketDataTickPayload& payload
) {
    if (seq_num == expected_seq_) {
        ++expected_seq_;
        ++total_packets_processed_;
        if (on_tick_) {
            on_tick_(payload, seq_num, timestamp_ns);
        }
        drain_buffered_packets();
    } else if (seq_num > expected_seq_) {
        pending_buffer_[seq_num] = BufferedPacket{seq_num, timestamp_ns, payload};
    }
}

void GapRecoveryTracker::drain_buffered_packets() {
    while (!pending_buffer_.empty() && pending_buffer_.begin()->first == expected_seq_) {
        auto it = pending_buffer_.begin();
        const auto& pkt = it->second;

        ++expected_seq_;
        ++total_packets_processed_;
        if (on_tick_) {
            on_tick_(pkt.payload, pkt.seq_num, pkt.timestamp_ns);
        }

        pending_buffer_.erase(it);
    }
}

void GapRecoveryTracker::store_historical_packet(uint64_t seq_num, const protocol::MarketDataTickPayload& payload) {
    size_t idx = seq_num % HISTORY_CAPACITY;
    history_cache_[idx].seq_num = seq_num;
    history_cache_[idx].payload = payload;
}

std::optional<protocol::MarketDataTickPayload> GapRecoveryTracker::get_historical_packet(uint64_t seq_num) const {
    size_t idx = seq_num % HISTORY_CAPACITY;
    if (history_cache_[idx].seq_num == seq_num) {
        return history_cache_[idx].payload;
    }
    return std::nullopt;
}

} // namespace quant::market_data
