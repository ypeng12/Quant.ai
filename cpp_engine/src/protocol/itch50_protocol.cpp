#include "../../include/protocol/itch50_protocol.hpp"

namespace quant::protocol::itch50 {

std::string_view ITCH50Decoder::decode_symbol(const char stock[8]) noexcept {
    size_t len = 0;
    while (len < 8 && stock[len] != ' ' && stock[len] != '\0') {
        ++len;
    }
    return std::string_view(stock, len);
}

bool ITCH50Decoder::decode_add_order(std::span<const uint8_t> buffer, DecodedAddOrder& out) noexcept {
    if (buffer.size() < sizeof(AddOrderMsg)) return false;

    const auto* msg = reinterpret_cast<const AddOrderMsg*>(buffer.data());
    if (msg->msg_type != 'A') return false;

    out.stock_locate = be16_to_cpu(msg->stock_locate);
    out.timestamp_ns = be48_to_cpu(msg->timestamp);
    out.order_ref_num = be64_to_cpu(msg->order_ref_num);
    out.side = msg->buy_sell_indicator;
    out.shares = be32_to_cpu(msg->shares);
    out.symbol = decode_symbol(msg->stock);
    out.price = static_cast<double>(be32_to_cpu(msg->price)) / 10000.0;

    return true;
}

bool ITCH50Decoder::decode_order_executed(std::span<const uint8_t> buffer, DecodedOrderExecuted& out) noexcept {
    if (buffer.size() < sizeof(OrderExecutedMsg)) return false;

    const auto* msg = reinterpret_cast<const OrderExecutedMsg*>(buffer.data());
    if (msg->msg_type != 'E') return false;

    out.stock_locate = be16_to_cpu(msg->stock_locate);
    out.timestamp_ns = be48_to_cpu(msg->timestamp);
    out.order_ref_num = be64_to_cpu(msg->order_ref_num);
    out.executed_shares = be32_to_cpu(msg->executed_shares);
    out.match_number = be64_to_cpu(msg->match_number);

    return true;
}

bool ITCH50Decoder::decode_order_cancel(std::span<const uint8_t> buffer, DecodedOrderCancel& out) noexcept {
    if (buffer.size() < sizeof(OrderCancelMsg)) return false;

    const auto* msg = reinterpret_cast<const OrderCancelMsg*>(buffer.data());
    if (msg->msg_type != 'X') return false;

    out.stock_locate = be16_to_cpu(msg->stock_locate);
    out.timestamp_ns = be48_to_cpu(msg->timestamp);
    out.order_ref_num = be64_to_cpu(msg->order_ref_num);
    out.canceled_shares = be32_to_cpu(msg->canceled_shares);

    return true;
}

bool ITCH50Decoder::decode_order_replace(std::span<const uint8_t> buffer, DecodedOrderReplace& out) noexcept {
    if (buffer.size() < sizeof(OrderReplaceMsg)) return false;

    const auto* msg = reinterpret_cast<const OrderReplaceMsg*>(buffer.data());
    if (msg->msg_type != 'U') return false;

    out.stock_locate = be16_to_cpu(msg->stock_locate);
    out.timestamp_ns = be48_to_cpu(msg->timestamp);
    out.orig_order_ref_num = be64_to_cpu(msg->orig_order_ref_num);
    out.new_order_ref_num = be64_to_cpu(msg->new_order_ref_num);
    out.shares = be32_to_cpu(msg->shares);
    out.price = static_cast<double>(be32_to_cpu(msg->price)) / 10000.0;

    return true;
}

} // namespace quant::protocol::itch50
