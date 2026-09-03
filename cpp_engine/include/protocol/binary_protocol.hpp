#pragma once

#include <cstdint>
#include <span>
#include <string_view>
#include <cstring>
#include <optional>
#include <tuple>
#include "../core/types.hpp"

namespace quant::protocol {

constexpr uint16_t PROTOCOL_MAGIC = 0x5154; // 'Q' 'T' (Quant Trading)

enum class MessageType : uint8_t {
    MARKET_DATA_TICK = 0x01,
    NEW_ORDER_SINGLE = 0x02,
    ORDER_CANCEL_REQ = 0x03,
    EXECUTION_REPORT = 0x04,
    HEARTBEAT        = 0x05,
    GAP_RECOVERY_REQ = 0x06,
    GAP_RECOVERY_RES = 0x07
};

#pragma pack(push, 1)

// Standard 19-byte protocol framing header
struct FrameHeader {
    uint16_t magic{PROTOCOL_MAGIC};
    uint8_t msg_type{0};
    uint16_t body_len{0};
    uint64_t seq_num{0};
    uint64_t timestamp_ns{0};
};

struct MarketDataTickPayload {
    core::Symbol symbol;
    int64_t bid_price_raw{0};
    int64_t ask_price_raw{0};
    uint32_t bid_qty{0};
    uint32_t ask_qty{0};
    int64_t last_price_raw{0};
    uint32_t last_qty{0};
};

struct NewOrderSinglePayload {
    core::ClientId client_id{0};
    core::ClientOrderId client_order_id{0};
    core::Symbol symbol;
    uint8_t side{0};         // core::Side
    uint8_t order_type{0};    // core::OrderType
    int64_t price_raw{0};
    uint32_t qty{0};
};

struct OrderCancelReqPayload {
    core::ClientId client_id{0};
    core::ClientOrderId client_order_id{0};
    core::ClientOrderId orig_client_order_id{0};
    core::Symbol symbol;
};

struct ExecutionReportPayload {
    core::ClientId client_id{0};
    core::ClientOrderId client_order_id{0};
    core::OrderId engine_order_id{0};
    uint64_t exec_id{0};
    uint8_t exec_type{0};     // core::ExecType
    int64_t fill_price_raw{0};
    uint32_t fill_qty{0};
    uint32_t leaves_qty{0};
    uint8_t reject_reason{0}; // core::RejectReason
};

struct HeartbeatPayload {
    uint64_t ping_timestamp_ns{0};
};

struct GapRecoveryReqPayload {
    core::ClientId client_id{0};
    uint64_t from_seq{0};
    uint64_t to_seq{0};
};

#pragma pack(pop)

// Maximum single message frame size (for network buffers)
constexpr size_t MAX_FRAME_SIZE = 128;

class BinaryProtocol {
public:
    /**
     * Parse header from raw buffer using C++20 std::span.
     * Returns std::nullopt if buffer is smaller than FrameHeader or magic mismatch.
     */
    static std::optional<FrameHeader> parse_header(std::span<const uint8_t> buffer) noexcept;

    /**
     * Serialize a complete message (Header + Payload) into destination buffer.
     * Returns total bytes written, or 0 if buffer too small.
     */
    template <typename PayloadType>
    static size_t serialize_message(
        std::span<uint8_t> dest,
        MessageType msg_type,
        uint64_t seq_num,
        uint64_t timestamp_ns,
        const PayloadType& payload
    ) noexcept {
        constexpr size_t total_size = sizeof(FrameHeader) + sizeof(PayloadType);
        if (dest.size() < total_size) return 0;

        FrameHeader hdr;
        hdr.magic = PROTOCOL_MAGIC;
        hdr.msg_type = static_cast<uint8_t>(msg_type);
        hdr.body_len = static_cast<uint16_t>(sizeof(PayloadType));
        hdr.seq_num = seq_num;
        hdr.timestamp_ns = timestamp_ns;

        std::memcpy(dest.data(), &hdr, sizeof(FrameHeader));
        std::memcpy(dest.data() + sizeof(FrameHeader), &payload, sizeof(PayloadType));
        return total_size;
    }

    /**
     * Zero-copy cast payload from span buffer.
     * Returns pointer to payload inside the span, or nullptr if length check fails.
     */
    template <typename PayloadType>
    static const PayloadType* parse_payload(std::span<const uint8_t> buffer) noexcept {
        constexpr size_t total_size = sizeof(FrameHeader) + sizeof(PayloadType);
        if (buffer.size() < total_size) return nullptr;

        const auto* hdr = reinterpret_cast<const FrameHeader*>(buffer.data());
        if (hdr->magic != PROTOCOL_MAGIC || hdr->body_len != sizeof(PayloadType)) {
            return nullptr;
        }

        return reinterpret_cast<const PayloadType*>(buffer.data() + sizeof(FrameHeader));
    }
};

} // namespace quant::protocol
