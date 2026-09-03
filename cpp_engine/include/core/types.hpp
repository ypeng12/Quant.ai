#pragma once

#include <cstdint>
#include <concepts>
#include <string_view>
#include <string>
#include <compare>
#include <iostream>

namespace quant::core {

// Strong ID types
using OrderId = uint64_t;
using ClientId = uint32_t;
using ClientOrderId = uint64_t;
using SequenceNum = uint64_t;
using TimestampNs = uint64_t;
using Quantity = uint32_t;

// Side of the book / order
enum class Side : uint8_t {
    BUY = 1,
    SELL = 2,
    UNKNOWN = 0
};

inline const char* side_to_string(Side side) noexcept {
    switch (side) {
        case Side::BUY: return "BUY";
        case Side::SELL: return "SELL";
        default: return "UNKNOWN";
    }
}

// Order type
enum class OrderType : uint8_t {
    LIMIT = 1,
    MARKET = 2,
    IOC = 3,       // Immediate or Cancel
    FOK = 4,       // Fill or Kill
    UNKNOWN = 0
};

// Execution / report status
enum class ExecType : uint8_t {
    NEW = 1,
    PARTIAL_FILL = 2,
    FILL = 3,
    CANCELED = 4,
    REJECTED = 5,
    EXPIRED = 6
};

// Rejection reasons for risk / validation
enum class RejectReason : uint8_t {
    NONE = 0,
    INVALID_PRICE = 1,
    INVALID_QUANTITY = 2,
    ORDER_NOT_FOUND = 3,
    DUPLICATE_ORDER_ID = 4,
    RISK_NOTIONAL_EXCEEDED = 5,
    RISK_PRICE_COLLAR_VIOLATED = 6,
    RISK_RATE_LIMIT_EXCEEDED = 7,
    RISK_POSITION_LIMIT_EXCEEDED = 8,
    INSUFFICIENT_LIQUIDITY = 9
};

/**
 * Fixed-point Price representation (scaled by 10^4 = 10,000, i.e., 4 decimal places).
 * Eliminates floating point rounding errors and non-determinism across compilers and hardware.
 */
class Price {
public:
    static constexpr int64_t SCALE = 10000;

    constexpr Price() noexcept : raw_(0) {}
    constexpr explicit Price(int64_t raw_scaled) noexcept : raw_(raw_scaled) {}

    static constexpr Price from_double(double value) noexcept {
        return Price(static_cast<int64_t>(value * SCALE + (value >= 0 ? 0.5 : -0.5)));
    }

    static constexpr Price from_raw(int64_t raw) noexcept {
        return Price(raw);
    }

    constexpr double to_double() const noexcept {
        return static_cast<double>(raw_) / SCALE;
    }

    constexpr int64_t raw() const noexcept { return raw_; }

    constexpr auto operator<=>(const Price&) const noexcept = default;
    constexpr bool operator==(const Price&) const noexcept = default;

    constexpr Price operator+(Price other) const noexcept { return Price(raw_ + other.raw_); }
    constexpr Price operator-(Price other) const noexcept { return Price(raw_ - other.raw_); }
    constexpr Price& operator+=(Price other) noexcept { raw_ += other.raw_; return *this; }
    constexpr Price& operator-=(Price other) noexcept { raw_ -= other.raw_; return *this; }

    constexpr bool is_zero() const noexcept { return raw_ == 0; }
    constexpr bool is_positive() const noexcept { return raw_ > 0; }

private:
    int64_t raw_;
};

// C++20 Concepts
template <typename T>
concept MarketDataPacketConcept = requires(T pkt) {
    { pkt.seq_num } -> std::convertible_to<SequenceNum>;
    { pkt.timestamp_ns } -> std::convertible_to<TimestampNs>;
};

template <typename T>
concept OrderConcept = requires(T order) {
    { order.order_id } -> std::convertible_to<OrderId>;
    { order.side } -> std::convertible_to<Side>;
    { order.price } -> std::convertible_to<Price>;
    { order.qty } -> std::convertible_to<Quantity>;
};

template <typename T>
concept Serializable = requires(T val, uint8_t* dst, const uint8_t* src, size_t len) {
    { val.serialize(dst, len) } -> std::convertible_to<size_t>;
    { val.deserialize(src, len) } -> std::convertible_to<bool>;
};

// Symbol representation (8-byte fixed ASCII, e.g. "AAPL\0\0\0\0")
struct Symbol {
    std::array<char, 8> data{0, 0, 0, 0, 0, 0, 0, 0};

    constexpr Symbol() noexcept = default;
    constexpr Symbol(const char* str) noexcept {
        for (size_t i = 0; i < 8 && str[i] != '\0'; ++i) {
            data[i] = str[i];
        }
    }
    constexpr Symbol(std::string_view sv) noexcept {
        size_t n = sv.size() < 8 ? sv.size() : 8;
        for (size_t i = 0; i < n; ++i) {
            data[i] = sv[i];
        }
    }

    constexpr std::string_view view() const noexcept {
        size_t len = 0;
        while (len < 8 && data[len] != '\0' && data[len] != ' ') {
            ++len;
        }
        return std::string_view(data.data(), len);
    }

    constexpr bool operator==(const Symbol& other) const noexcept {
        for (size_t i = 0; i < 8; ++i) {
            if (data[i] != other.data[i]) return false;
        }
        return true;
    }

    constexpr bool operator<(const Symbol& other) const noexcept {
        for (size_t i = 0; i < 8; ++i) {
            if (data[i] < other.data[i]) return true;
            if (data[i] > other.data[i]) return false;
        }
        return false;
    }
};

} // namespace quant::core
