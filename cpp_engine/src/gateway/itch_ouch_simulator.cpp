#include "../../include/gateway/itch_ouch_simulator.hpp"
#include <cstring>
#include <iostream>

namespace quant::gateway {

ITCHOUCHExchangeSimulator::ITCHOUCHExchangeSimulator(core::Symbol symbol, ITCHBroadcastCallback on_itch)
    : symbol_(symbol), on_itch_(std::move(on_itch)), matching_engine_(symbol) {}

void ITCHOUCHExchangeSimulator::broadcast_itch(const void* data, size_t len) {
    const auto* byte_ptr = static_cast<const uint8_t*>(data);
    std::vector<uint8_t> frame(byte_ptr, byte_ptr + len);
    emitted_itch_feed_.push_back(frame);

    if (on_itch_) {
        on_itch_(std::span<const uint8_t>(frame.data(), frame.size()));
    }
}

std::vector<uint8_t> ITCHOUCHExchangeSimulator::process_enter_order(const EnterOrderMsg& enter_msg) {
    ++total_orders_;
    uint64_t now_ns = core::TimeUtils::now_ns();
    std::string token(OUCHCodec::token_view(enter_msg.order_token));

    // Reject checks
    if (enter_msg.shares == 0 || enter_msg.price == 0) {
        OrderRejectedMsg rej;
        rej.timestamp_ns = now_ns;
        std::memcpy(rej.order_token, enter_msg.order_token, 14);
        rej.reason = (enter_msg.shares == 0) ? 'S' : 'P';
        std::vector<uint8_t> out(sizeof(rej));
        std::memcpy(out.data(), &rej, sizeof(rej));
        return out;
    }

    uint64_t ref_num = next_order_ref_num_++;
    uint64_t engine_order_id = ref_num;

    token_to_meta_[token] = TokenMeta{
        engine_order_id,
        ref_num,
        enter_msg.buy_sell,
        enter_msg.shares,
        enter_msg.price
    };
    ref_to_token_[ref_num] = token;

    // 1. Emit OUCH Order Accepted ('A')
    OrderAcceptedMsg accepted;
    accepted.timestamp_ns = now_ns;
    std::memcpy(accepted.order_token, enter_msg.order_token, 14);
    accepted.buy_sell = enter_msg.buy_sell;
    accepted.shares = enter_msg.shares;
    std::memcpy(accepted.stock, enter_msg.stock, 8);
    accepted.price = enter_msg.price;
    accepted.time_in_force = enter_msg.time_in_force;
    std::memcpy(accepted.firm, enter_msg.firm, 4);
    accepted.display = enter_msg.display;
    accepted.order_ref_num = ref_num;

    std::vector<uint8_t> ouch_response(sizeof(accepted));
    std::memcpy(ouch_response.data(), &accepted, sizeof(accepted));

    // 2. Broadcast ITCH Add Order ('A')
    AddOrderMsg itch_add;
    itch_add.msg_type = 'A';
    itch_add.stock_locate = be16_to_cpu(1);
    itch_add.tracking_num = be16_to_cpu(1);
    cpu_to_be48(now_ns, itch_add.timestamp);
    itch_add.order_ref_num = be64_to_cpu(ref_num);
    itch_add.buy_sell_indicator = enter_msg.buy_sell;
    itch_add.shares = be32_to_cpu(enter_msg.shares);
    std::memcpy(itch_add.stock, enter_msg.stock, 8);
    itch_add.price = be32_to_cpu(enter_msg.price);

    broadcast_itch(&itch_add, sizeof(itch_add));

    // 3. Process matching
    core::Side side = (enter_msg.buy_sell == 'B') ? core::Side::BUY : core::Side::SELL;
    core::OrderType otype = (enter_msg.time_in_force == 0) ? core::OrderType::IOC : core::OrderType::LIMIT;
    core::Price price = core::Price::from_raw(enter_msg.price);

    matching_engine_.set_execution_callback([&](const protocol::ExecutionReportPayload& rep) {
        if (rep.exec_type == static_cast<uint8_t>(core::ExecType::FILL) ||
            rep.exec_type == static_cast<uint8_t>(core::ExecType::PARTIAL_FILL)) {
            
            // Broadcast ITCH Order Executed ('E')
            protocol::itch50::OrderExecutedMsg itch_exec;
            itch_exec.msg_type = 'E';
            itch_exec.stock_locate = be16_to_cpu(1);
            itch_exec.tracking_num = be16_to_cpu(1);
            cpu_to_be48(core::TimeUtils::now_ns(), itch_exec.timestamp);
            itch_exec.order_ref_num = be64_to_cpu(ref_num);
            itch_exec.executed_shares = be32_to_cpu(rep.fill_qty);
            itch_exec.match_number = be64_to_cpu(next_match_num_++);

            broadcast_itch(&itch_exec, sizeof(itch_exec));
        }
    });

    matching_engine_.process_new_order(1, ref_num, side, otype, price, enter_msg.shares, now_ns);

    return ouch_response;
}

std::vector<uint8_t> ITCHOUCHExchangeSimulator::process_cancel_order(const CancelOrderMsg& cancel_msg) {
    uint64_t now_ns = core::TimeUtils::now_ns();
    std::string token(OUCHCodec::token_view(cancel_msg.order_token));

    auto it = token_to_meta_.find(token);
    if (it == token_to_meta_.end()) {
        OrderRejectedMsg rej;
        rej.timestamp_ns = now_ns;
        std::memcpy(rej.order_token, cancel_msg.order_token, 14);
        rej.reason = 'C';
        std::vector<uint8_t> out(sizeof(rej));
        std::memcpy(out.data(), &rej, sizeof(rej));
        return out;
    }

    uint32_t cancel_shares = (cancel_msg.shares > 0 && cancel_msg.shares <= it->second.leaves_qty)
                             ? cancel_msg.shares : it->second.leaves_qty;

    // 1. Cancel in matching engine
    matching_engine_.cancel_order(1, it->second.order_ref_num, it->second.engine_order_id, now_ns);

    // 2. Broadcast ITCH Order Cancel ('X')
    OrderCancelMsg itch_cancel;
    itch_cancel.msg_type = 'X';
    itch_cancel.stock_locate = be16_to_cpu(1);
    itch_cancel.tracking_num = be16_to_cpu(1);
    cpu_to_be48(now_ns, itch_cancel.timestamp);
    itch_cancel.order_ref_num = be64_to_cpu(it->second.order_ref_num);
    itch_cancel.canceled_shares = be32_to_cpu(cancel_shares);

    broadcast_itch(&itch_cancel, sizeof(itch_cancel));

    // 3. Emit OUCH Order Canceled ('C')
    OrderCanceledMsg ouch_canceled;
    ouch_canceled.timestamp_ns = now_ns;
    std::memcpy(ouch_canceled.order_token, cancel_msg.order_token, 14);
    ouch_canceled.decrement_shares = cancel_shares;
    ouch_canceled.reason = 'U';

    std::vector<uint8_t> out(sizeof(ouch_canceled));
    std::memcpy(out.data(), &ouch_canceled, sizeof(ouch_canceled));

    it->second.leaves_qty -= cancel_shares;
    if (it->second.leaves_qty == 0) {
        token_to_meta_.erase(it);
    }

    return out;
}

std::vector<uint8_t> ITCHOUCHExchangeSimulator::process_replace_order(const ReplaceOrderMsg& replace_msg) {
    uint64_t now_ns = core::TimeUtils::now_ns();
    std::string token(OUCHCodec::token_view(replace_msg.existing_order_token));

    auto it = token_to_meta_.find(token);
    if (it == token_to_meta_.end()) {
        OrderRejectedMsg rej;
        rej.timestamp_ns = now_ns;
        std::memcpy(rej.order_token, replace_msg.existing_order_token, 14);
        rej.reason = 'C';
        std::vector<uint8_t> out(sizeof(rej));
        std::memcpy(out.data(), &rej, sizeof(rej));
        return out;
    }

    uint64_t orig_ref = it->second.order_ref_num;
    uint64_t new_ref = next_order_ref_num_++;

    // Cancel old order
    matching_engine_.cancel_order(1, orig_ref, it->second.engine_order_id, now_ns);

    // Broadcast ITCH Order Replace ('U')
    OrderReplaceMsg itch_replace;
    itch_replace.msg_type = 'U';
    itch_replace.stock_locate = be16_to_cpu(1);
    itch_replace.tracking_num = be16_to_cpu(1);
    cpu_to_be48(now_ns, itch_replace.timestamp);
    itch_replace.orig_order_ref_num = be64_to_cpu(orig_ref);
    itch_replace.new_order_ref_num = be64_to_cpu(new_ref);
    itch_replace.shares = be32_to_cpu(replace_msg.shares);
    itch_replace.price = be32_to_cpu(replace_msg.price);

    broadcast_itch(&itch_replace, sizeof(itch_replace));

    // Submit new limit order
    core::Side side = (it->second.buy_sell == 'B') ? core::Side::BUY : core::Side::SELL;
    matching_engine_.process_new_order(1, new_ref, side, core::OrderType::LIMIT,
                                       core::Price::from_raw(replace_msg.price), replace_msg.shares, now_ns);

    it->second.order_ref_num = new_ref;
    it->second.leaves_qty = replace_msg.shares;
    it->second.price = replace_msg.price;

    OrderAcceptedMsg accepted;
    accepted.timestamp_ns = now_ns;
    std::memcpy(accepted.order_token, replace_msg.existing_order_token, 14);
    accepted.buy_sell = it->second.buy_sell;
    accepted.shares = replace_msg.shares;
    std::memcpy(accepted.stock, symbol_.data.data(), 8);
    accepted.price = replace_msg.price;
    accepted.time_in_force = 99999;
    std::memset(accepted.firm, ' ', 4);
    accepted.display = 'Y';
    accepted.order_ref_num = new_ref;

    std::vector<uint8_t> out(sizeof(accepted));
    std::memcpy(out.data(), &accepted, sizeof(accepted));
    return out;
}

std::vector<uint8_t> ITCHOUCHExchangeSimulator::generate_snapshot_packet() {
    order_book::L2Snapshot snap;
    matching_engine_.book().get_l2_snapshot(snap);

    SnapshotHeaderMsg hdr;
    hdr.msg_type = 'Z';
    hdr.stock_locate = be16_to_cpu(1);
    hdr.sequence_num = be64_to_cpu(next_order_ref_num_);
    std::memcpy(hdr.stock, symbol_.data.data(), 8);
    hdr.bid_levels_count = be32_to_cpu(static_cast<uint32_t>(snap.bid_count));
    hdr.ask_levels_count = be32_to_cpu(static_cast<uint32_t>(snap.ask_count));

    size_t total_size = sizeof(SnapshotHeaderMsg) + (snap.bid_count + snap.ask_count) * sizeof(order_book::L2Level);
    std::vector<uint8_t> packet(total_size);
    std::memcpy(packet.data(), &hdr, sizeof(SnapshotHeaderMsg));

    size_t offset = sizeof(SnapshotHeaderMsg);
    for (size_t i = 0; i < snap.bid_count; ++i) {
        std::memcpy(packet.data() + offset, &snap.bids[i], sizeof(order_book::L2Level));
        offset += sizeof(order_book::L2Level);
    }
    for (size_t i = 0; i < snap.ask_count; ++i) {
        std::memcpy(packet.data() + offset, &snap.asks[i], sizeof(order_book::L2Level));
        offset += sizeof(order_book::L2Level);
    }

    return packet;
}

} // namespace quant::gateway
