#pragma once

#include <cstdint>
#include <span>
#include <string_view>
#include <cstring>
#include <optional>
#include <array>

namespace quant::protocol::itch50 {

// Byte swapping utilities for Big-Endian Nasdaq ITCH 5.0 wire protocol
inline uint16_t be16_to_cpu(uint16_t v) noexcept { return __builtin_bswap16(v); }
inline uint32_t be32_to_cpu(uint32_t v) noexcept { return __builtin_bswap32(v); }
inline uint64_t be64_to_cpu(uint64_t v) noexcept { return __builtin_bswap64(v); }

inline uint64_t be48_to_cpu(const uint8_t* p) noexcept {
    return (static_cast<uint64_t>(p[0]) << 40) |
           (static_cast<uint64_t>(p[1]) << 32) |
           (static_cast<uint64_t>(p[2]) << 24) |
           (static_cast<uint64_t>(p[3]) << 16) |
           (static_cast<uint64_t>(p[4]) << 8)  |
           (static_cast<uint64_t>(p[5]));
}

inline void cpu_to_be48(uint64_t v, uint8_t* p) noexcept {
    p[0] = static_cast<uint8_t>((v >> 40) & 0xFF);
    p[1] = static_cast<uint8_t>((v >> 32) & 0xFF);
    p[2] = static_cast<uint8_t>((v >> 24) & 0xFF);
    p[3] = static_cast<uint8_t>((v >> 16) & 0xFF);
    p[4] = static_cast<uint8_t>((v >> 8) & 0xFF);
    p[5] = static_cast<uint8_t>(v & 0xFF);
}

#pragma pack(push, 1)

// 1. System Event Message ('S', 12 bytes)
struct SystemEventMsg {
    char msg_type{'S'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    char event_code{'O'}; // 'O'=Start of Messages, 'S'=Start System, 'Q'=Start Market, 'M'=End Market, 'E'=End System, 'C'=End Messages
};

// 2. Stock Directory ('R', 39 bytes)
struct StockDirectoryMsg {
    char msg_type{'R'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    char stock[8]{' '};
    char market_category{'Q'};
    char financial_status{'N'};
    uint32_t round_lot_size{0};
    char round_lots_only{'N'};
    char issue_classification{'C'};
    char issue_sub_type[2]{'S', 'I'};
    char authenticity{'P'};
    char short_sale_threshold{'N'};
    char ipo_flag{'N'};
    char luld_tier{'1'};
    char etp_flag{'N'};
    uint32_t etp_leverage{0};
    char inverse_indicator{'N'};
};

// 3. Stock Trading Action ('H', 25 bytes)
struct StockTradingActionMsg {
    char msg_type{'H'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    char stock[8]{' '};
    char trading_state{'T'}; // 'H'=Halted, 'P'=Paused, 'T'=Trading
    char reserved{' '};
    char reason[4]{' ', ' ', ' ', ' '};
};

// 4. Add Order Message ('A', 36 bytes)
struct AddOrderMsg {
    char msg_type{'A'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t order_ref_num{0};
    char buy_sell_indicator{'B'}; // 'B'=Buy, 'S'=Sell
    uint32_t shares{0};
    char stock[8]{' '};
    uint32_t price{0}; // Price (4 decimal fixed point, scaled by 10,000)
};

// 5. Add Order with MPID ('F', 40 bytes)
struct AddOrderMPIDMsg {
    char msg_type{'F'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t order_ref_num{0};
    char buy_sell_indicator{'B'};
    uint32_t shares{0};
    char stock[8]{' '};
    uint32_t price{0};
    char attribution[4]{' ', ' ', ' ', ' '};
};

// 6. Order Executed ('E', 31 bytes)
struct OrderExecutedMsg {
    char msg_type{'E'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t order_ref_num{0};
    uint32_t executed_shares{0};
    uint64_t match_number{0};
};

// 7. Order Executed with Price ('C', 36 bytes)
struct OrderExecutedWithPriceMsg {
    char msg_type{'C'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t order_ref_num{0};
    uint32_t executed_shares{0};
    uint64_t match_number{0};
    char printable{'Y'};
    uint32_t execution_price{0};
};

// 8. Order Cancel ('X', 23 bytes)
struct OrderCancelMsg {
    char msg_type{'X'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t order_ref_num{0};
    uint32_t canceled_shares{0};
};

// 9. Order Delete ('D', 19 bytes)
struct OrderDeleteMsg {
    char msg_type{'D'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t order_ref_num{0};
};

// 10. Order Replace ('U', 35 bytes)
struct OrderReplaceMsg {
    char msg_type{'U'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t orig_order_ref_num{0};
    uint64_t new_order_ref_num{0};
    uint32_t shares{0};
    uint32_t price{0};
};

// 11. Trade Message Non-Cross ('P', 44 bytes)
struct TradeMsg {
    char msg_type{'P'};
    uint16_t stock_locate{0};
    uint16_t tracking_num{0};
    uint8_t timestamp[6]{0};
    uint64_t order_ref_num{0};
    char buy_sell_indicator{'B'};
    uint32_t shares{0};
    char stock[8]{' '};
    uint32_t price{0};
    uint64_t match_number{0};
};

// 12. Snapshot Header for state recovery ('Z', 26 bytes)
struct SnapshotHeaderMsg {
    char msg_type{'Z'};
    uint16_t stock_locate{0};
    uint64_t sequence_num{0};
    char stock[8]{' '};
    uint32_t bid_levels_count{0};
    uint32_t ask_levels_count{0};
};

#pragma pack(pop)

// Decoded C++ Friendly In-Memory Structs
struct DecodedAddOrder {
    uint16_t stock_locate;
    uint64_t timestamp_ns;
    uint64_t order_ref_num;
    char side; // 'B' or 'S'
    uint32_t shares;
    std::string_view symbol;
    double price;
};

struct DecodedOrderExecuted {
    uint16_t stock_locate;
    uint64_t timestamp_ns;
    uint64_t order_ref_num;
    uint32_t executed_shares;
    uint64_t match_number;
};

struct DecodedOrderCancel {
    uint16_t stock_locate;
    uint64_t timestamp_ns;
    uint64_t order_ref_num;
    uint32_t canceled_shares;
};

struct DecodedOrderReplace {
    uint16_t stock_locate;
    uint64_t timestamp_ns;
    uint64_t orig_order_ref_num;
    uint64_t new_order_ref_num;
    uint32_t shares;
    double price;
};

class ITCH50Decoder {
public:
    static std::string_view decode_symbol(const char stock[8]) noexcept;

    static bool decode_add_order(std::span<const uint8_t> buffer, DecodedAddOrder& out) noexcept;
    static bool decode_order_executed(std::span<const uint8_t> buffer, DecodedOrderExecuted& out) noexcept;
    static bool decode_order_cancel(std::span<const uint8_t> buffer, DecodedOrderCancel& out) noexcept;
    static bool decode_order_replace(std::span<const uint8_t> buffer, DecodedOrderReplace& out) noexcept;

    // Fast message length lookup
    static constexpr size_t message_length(char msg_type) noexcept {
        switch (msg_type) {
            case 'S': return sizeof(SystemEventMsg);
            case 'R': return sizeof(StockDirectoryMsg);
            case 'H': return sizeof(StockTradingActionMsg);
            case 'A': return sizeof(AddOrderMsg);
            case 'F': return sizeof(AddOrderMPIDMsg);
            case 'E': return sizeof(OrderExecutedMsg);
            case 'C': return sizeof(OrderExecutedWithPriceMsg);
            case 'X': return sizeof(OrderCancelMsg);
            case 'D': return sizeof(OrderDeleteMsg);
            case 'U': return sizeof(OrderReplaceMsg);
            case 'P': return sizeof(TradeMsg);
            case 'Z': return sizeof(SnapshotHeaderMsg);
            default: return 0;
        }
    }
};

} // namespace quant::protocol::itch50
