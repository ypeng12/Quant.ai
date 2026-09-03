#pragma once

#include <cstdint>
#include <span>
#include <string_view>
#include <cstring>
#include <optional>
#include "itch50_protocol.hpp"

namespace quant::protocol::ouch {

using namespace itch50;

#pragma pack(push, 1)

// Inbound: Enter Order ('O', 47 bytes)
struct EnterOrderMsg {
    char msg_type{'O'};
    char order_token[14]{' '};
    char buy_sell{'B'};
    uint32_t shares{0};
    char stock[8]{' '};
    uint32_t price{0}; // 4 decimal fixed point
    uint32_t time_in_force{0}; // 0 = IOC, 99999 = Day
    char firm[4]{' '};
    char display{'Y'};
    char capacity{'A'};
    char intermarket_sweep{'N'};
    uint32_t min_quantity{0};
    char cross_type{'N'};
};

// Inbound: Cancel Order ('X', 19 bytes)
struct CancelOrderMsg {
    char msg_type{'X'};
    char order_token[14]{' '};
    uint32_t shares{0};
};

// Inbound: Replace Order ('U', 27 bytes)
struct ReplaceOrderMsg {
    char msg_type{'U'};
    char existing_order_token[14]{' '};
    uint32_t shares{0};
    uint32_t price{0};
};

// Outbound: Order Accepted ('A', 58 bytes)
struct OrderAcceptedMsg {
    char msg_type{'A'};
    uint64_t timestamp_ns{0};
    char order_token[14]{' '};
    char buy_sell{'B'};
    uint32_t shares{0};
    char stock[8]{' '};
    uint32_t price{0};
    uint32_t time_in_force{0};
    char firm[4]{' '};
    char display{'Y'};
    uint64_t order_ref_num{0};
};

// Outbound: Order Canceled ('C', 28 bytes)
struct OrderCanceledMsg {
    char msg_type{'C'};
    uint64_t timestamp_ns{0};
    char order_token[14]{' '};
    uint32_t decrement_shares{0};
    char reason{'U'}; // 'U'=User request, 'I'=IOC unexecuted, 'T'=Timeout
};

// Outbound: Order Executed ('E', 41 bytes)
struct OrderExecutedMsg {
    char msg_type{'E'};
    uint64_t timestamp_ns{0};
    char order_token[14]{' '};
    uint32_t executed_shares{0};
    uint32_t execution_price{0};
    char liquidity_flag{'A'}; // 'A'=Added, 'R'=Removed
    uint64_t match_number{0};
};

// Outbound: Order Rejected ('J', 24 bytes)
struct OrderRejectedMsg {
    char msg_type{'J'};
    uint64_t timestamp_ns{0};
    char order_token[14]{' '};
    char reason{'C'}; // 'C'=Closed, 'P'=Invalid price, 'S'=Invalid shares, 'R'=Risk limit
};

#pragma pack(pop)

class OUCHCodec {
public:
    static std::string_view token_view(const char token[14]) noexcept {
        size_t len = 0;
        while (len < 14 && token[len] != ' ' && token[len] != '\0') ++len;
        return std::string_view(token, len);
    }

    static void set_token(char dest[14], std::string_view token) noexcept {
        std::memset(dest, ' ', 14);
        size_t n = std::min(token.size(), size_t(14));
        std::memcpy(dest, token.data(), n);
    }

    static void set_symbol(char dest[8], std::string_view sym) noexcept {
        std::memset(dest, ' ', 8);
        size_t n = std::min(sym.size(), size_t(8));
        std::memcpy(dest, sym.data(), n);
    }
};

} // namespace quant::protocol::ouch
