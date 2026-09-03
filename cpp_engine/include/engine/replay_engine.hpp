#pragma once

#include <cstdint>
#include <string>
#include <fstream>
#include <vector>
#include <functional>
#include <span>
#include "../core/types.hpp"
#include "../protocol/binary_protocol.hpp"
#include "../order_book/matching_engine.hpp"

namespace quant::engine {

constexpr uint32_t JOURNAL_MAGIC = 0x514A4E4C; // 'QJNL' (Quant Journal)

#pragma pack(push, 1)
struct JournalHeader {
    uint32_t magic{JOURNAL_MAGIC};
    uint32_t version{1};
    uint64_t start_time_ns{0};
};

struct JournalRecordHeader {
    uint64_t timestamp_ns{0};
    uint64_t seq_num{0};
    uint8_t msg_type{0};
    uint16_t payload_len{0};
};
#pragma pack(pop)

/**
 * High-performance binary event journal recorder for deterministic audit & replay.
 */
class JournalRecorder {
public:
    explicit JournalRecorder(const std::string& journal_path);
    ~JournalRecorder();

    bool open();
    void close();

    template <typename PayloadType>
    bool record_event(
        protocol::MessageType msg_type,
        uint64_t seq_num,
        uint64_t timestamp_ns,
        const PayloadType& payload
    ) {
        if (!out_file_.is_open()) return false;

        JournalRecordHeader rec;
        rec.timestamp_ns = timestamp_ns;
        rec.seq_num = seq_num;
        rec.msg_type = static_cast<uint8_t>(msg_type);
        rec.payload_len = sizeof(PayloadType);

        out_file_.write(reinterpret_cast<const char*>(&rec), sizeof(JournalRecordHeader));
        out_file_.write(reinterpret_cast<const char*>(&payload), sizeof(PayloadType));
        ++total_records_;
        return true;
    }

    void flush() {
        if (out_file_.is_open()) out_file_.flush();
    }

    [[nodiscard]] uint64_t total_records() const noexcept { return total_records_; }

private:
    std::string path_;
    std::ofstream out_file_;
    uint64_t total_records_{0};
};

/**
 * Deterministic Replay Engine.
 * Reads binary journal file and replays events into matching engine with bit-for-bit state verification.
 */
class ReplayEngine {
public:
    using EventDispatchCallback = std::function<void(
        protocol::MessageType type,
        uint64_t seq,
        uint64_t ts,
        std::span<const uint8_t> payload
    )>;

    explicit ReplayEngine(const std::string& journal_path);

    bool replay(EventDispatchCallback on_event);

    /**
     * Deterministically replay into a MatchingEngine instance and verify state integrity.
     */
    bool replay_into_engine(order_book::MatchingEngine& engine);

    [[nodiscard]] uint64_t replayed_count() const noexcept { return replayed_count_; }

private:
    std::string path_;
    uint64_t replayed_count_{0};
};

} // namespace quant::engine
