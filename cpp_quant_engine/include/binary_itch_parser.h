// cpp_quant_engine/include/binary_itch_parser.h
#ifndef BINARY_ITCH_PARSER_H
#define BINARY_ITCH_PARSER_H

#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#pragma pack(push, 1)

// NASDAQ ITCH 5.0 Style Add Order Message (36 bytes)
struct AddOrderMsg {
    char message_type;      // 'A'
    uint16_t stock_locate;  // Locate Code
    uint16_t tracking_num;  // Tracking Number
    uint64_t timestamp;     // Nanoseconds since midnight
    uint64_t order_ref_num; // Unique Order Reference Number
    char buy_sell_indicator;// 'B' = Buy, 'S' = Sell
    uint32_t shares;        // Shares Quantity
    char stock[8];          // Ticker Symbol (padded with spaces)
    uint32_t price;         // Price in 4 decimal places (price / 10000.0)
};

// Order Executed Message (31 bytes)
struct OrderExecutedMsg {
    char message_type;      // 'E'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;
    uint64_t order_ref_num;
    uint32_t executed_shares;
    uint64_t match_number;
};

// Order Cancel Message (23 bytes)
struct OrderCancelMsg {
    char message_type;      // 'X'
    uint16_t stock_locate;
    uint16_t tracking_num;
    uint64_t timestamp;
    uint64_t order_ref_num;
    uint32_t cancelled_shares;
};

#pragma pack(pop)

class BinaryITCHParser {
public:
    static bool parseAddOrder(const uint8_t* buffer, size_t len, AddOrderMsg& msg) {
        if (len < sizeof(AddOrderMsg) || buffer[0] != 'A') return false;
        std::memcpy(&msg, buffer, sizeof(AddOrderMsg));
        return true;
    }

    static double decodePrice(uint32_t raw_price) {
        return static_cast<double>(raw_price) / 10000.0;
    }

    static std::string decodeTicker(const char stock[8]) {
        std::string ticker(stock, 8);
        size_t end = ticker.find_last_not_of(' ');
        return (end != std::string::npos) ? ticker.substr(0, end + 1) : ticker;
    }
};

#endif // BINARY_ITCH_PARSER_H
