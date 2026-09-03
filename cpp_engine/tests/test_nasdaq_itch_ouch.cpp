#include <gtest/gtest.h>
#include "../include/protocol/itch50_protocol.hpp"
#include "../include/protocol/ouch_protocol.hpp"
#include "../include/gateway/itch_ouch_simulator.hpp"

using namespace quant::protocol::itch50;
using namespace quant::protocol::ouch;
namespace itch50 = quant::protocol::itch50;
namespace ouch = quant::protocol::ouch;
using namespace quant::gateway;
using namespace quant::core;

// 1. Official Nasdaq TotalView-ITCH 5.0 Specification Byte Size Conformance
TEST(NasdaqITCHConformanceTest, OfficialSpecByteOffsets) {
    EXPECT_EQ(sizeof(SystemEventMsg), 12);
    EXPECT_EQ(sizeof(StockDirectoryMsg), 39);
    EXPECT_EQ(sizeof(StockTradingActionMsg), 25);
    EXPECT_EQ(sizeof(AddOrderMsg), 36);
    EXPECT_EQ(sizeof(AddOrderMPIDMsg), 40);
    EXPECT_EQ(sizeof(itch50::OrderExecutedMsg), 31);
    EXPECT_EQ(sizeof(OrderExecutedWithPriceMsg), 36);
    EXPECT_EQ(sizeof(OrderCancelMsg), 23);
    EXPECT_EQ(sizeof(OrderDeleteMsg), 19);
    EXPECT_EQ(sizeof(OrderReplaceMsg), 35);
    EXPECT_EQ(sizeof(TradeMsg), 44);
    // OUCH sizes
    EXPECT_EQ(sizeof(EnterOrderMsg), 48);
    EXPECT_EQ(sizeof(ouch::OrderExecutedMsg), 40);
    EXPECT_EQ(sizeof(OrderAcceptedMsg), 57);
    EXPECT_EQ(sizeof(OrderCanceledMsg), 28);
    EXPECT_EQ(sizeof(OrderRejectedMsg), 24);
}

// 2. Big-Endian Decoding & 48-Bit Timestamp Precision
TEST(NasdaqITCHConformanceTest, BigEndianTimestampAndPriceDecoding) {
    AddOrderMsg raw_wire{};
    raw_wire.msg_type = 'A';
    raw_wire.stock_locate = be16_to_cpu(101);
    raw_wire.tracking_num = be16_to_cpu(1);
    uint64_t expected_time_ns = 34200000000000ULL; // 9:30:00.000 AM
    cpu_to_be48(expected_time_ns, raw_wire.timestamp);
    raw_wire.order_ref_num = be64_to_cpu(888999111ULL);
    raw_wire.buy_sell_indicator = 'B';
    raw_wire.shares = be32_to_cpu(500);
    std::memcpy(raw_wire.stock, "NVDA    ", 8);
    raw_wire.price = be32_to_cpu(1255000); // $125.5000

    std::span<const uint8_t> span(reinterpret_cast<const uint8_t*>(&raw_wire), sizeof(raw_wire));
    DecodedAddOrder decoded{};
    ASSERT_TRUE(ITCH50Decoder::decode_add_order(span, decoded));

    EXPECT_EQ(decoded.stock_locate, 101);
    EXPECT_EQ(decoded.timestamp_ns, expected_time_ns);
    EXPECT_EQ(decoded.order_ref_num, 888999111ULL);
    EXPECT_EQ(decoded.side, 'B');
    EXPECT_EQ(decoded.shares, 500);
    EXPECT_EQ(decoded.symbol, "NVDA");
    EXPECT_DOUBLE_EQ(decoded.price, 125.50);
}

// 3. End-to-End Exchange Simulator: OUCH Order Entry -> ITCH 5.0 Feed & Snapshot
TEST(NasdaqITCHConformanceTest, ExchangeSimulatorOrderLifecycle) {
    std::vector<std::vector<uint8_t>> broadcasted_itch;
    ITCHOUCHExchangeSimulator simulator(Symbol("AAPL"), [&](std::span<const uint8_t> itch_msg) {
        broadcasted_itch.emplace_back(itch_msg.begin(), itch_msg.end());
    });

    // Step A: Client enters Limit Sell Order via OUCH
    EnterOrderMsg ouch_enter{};
    ouch_enter.msg_type = 'O';
    OUCHCodec::set_token(ouch_enter.order_token, "CLIENT_ORD_01");
    ouch_enter.buy_sell = 'S';
    ouch_enter.shares = 200;
    OUCHCodec::set_symbol(ouch_enter.stock, "AAPL");
    ouch_enter.price = 1800000; // $180.0000
    ouch_enter.time_in_force = 99999;

    auto resp_bytes = simulator.process_enter_order(ouch_enter);
    ASSERT_EQ(resp_bytes.size(), sizeof(OrderAcceptedMsg));

    const auto* accepted = reinterpret_cast<const OrderAcceptedMsg*>(resp_bytes.data());
    EXPECT_EQ(accepted->msg_type, 'A');
    EXPECT_EQ(OUCHCodec::token_view(accepted->order_token), "CLIENT_ORD_01");
    EXPECT_EQ(accepted->shares, 200);

    // Verify ITCH Add Order 'A' was broadcasted
    ASSERT_GE(broadcasted_itch.size(), 1);
    const auto* itch_add = reinterpret_cast<const AddOrderMsg*>(broadcasted_itch[0].data());
    EXPECT_EQ(itch_add->msg_type, 'A');
    EXPECT_EQ(itch_add->buy_sell_indicator, 'S');
    EXPECT_EQ(be32_to_cpu(itch_add->shares), 200);
    EXPECT_EQ(be32_to_cpu(itch_add->price), 1800000);

    // Step B: Client Replaces Order to $181.00 for 150 shares
    ReplaceOrderMsg ouch_replace{};
    ouch_replace.msg_type = 'U';
    OUCHCodec::set_token(ouch_replace.existing_order_token, "CLIENT_ORD_01");
    ouch_replace.shares = 150;
    ouch_replace.price = 1810000; // $181.0000

    auto replace_resp = simulator.process_replace_order(ouch_replace);
    ASSERT_EQ(replace_resp.size(), sizeof(OrderAcceptedMsg));

    // Verify ITCH Order Replace 'U' broadcasted
    ASSERT_GE(broadcasted_itch.size(), 2);
    const auto* itch_rep = reinterpret_cast<const OrderReplaceMsg*>(broadcasted_itch[1].data());
    EXPECT_EQ(itch_rep->msg_type, 'U');
    EXPECT_EQ(be32_to_cpu(itch_rep->shares), 150);
    EXPECT_EQ(be32_to_cpu(itch_rep->price), 1810000);

    // Step C: Generate Snapshot
    auto snapshot_packet = simulator.generate_snapshot_packet();
    ASSERT_GE(snapshot_packet.size(), sizeof(SnapshotHeaderMsg));
    const auto* snap_hdr = reinterpret_cast<const SnapshotHeaderMsg*>(snapshot_packet.data());
    EXPECT_EQ(snap_hdr->msg_type, 'Z');
    EXPECT_EQ(be32_to_cpu(snap_hdr->ask_levels_count), 1);
}
