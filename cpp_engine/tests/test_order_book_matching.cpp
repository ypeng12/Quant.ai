#include <gtest/gtest.h>
#include "../include/order_book/matching_engine.hpp"

using namespace quant::core;
using namespace quant::order_book;
using namespace quant::protocol;

TEST(OrderBookMatchingTest, BasicLimitOrderMatching) {
    std::vector<ExecutionReportPayload> reports;
    MatchingEngine engine(Symbol("TSLA"), [&](const ExecutionReportPayload& r) {
        reports.push_back(r);
    });

    // Maker: Sell 100 @ 250.00
    engine.process_new_order(1, 101, Side::SELL, OrderType::LIMIT, Price::from_double(250.0), 100, 1000);
    ASSERT_EQ(reports.size(), 1);
    EXPECT_EQ(reports[0].exec_type, static_cast<uint8_t>(ExecType::NEW));
    EXPECT_EQ(reports[0].leaves_qty, 100);

    // Taker: Buy 60 @ 250.00
    engine.process_new_order(2, 201, Side::BUY, OrderType::LIMIT, Price::from_double(250.0), 60, 2000);
    // Should trigger 2 reports: maker partial fill, taker fill
    ASSERT_EQ(reports.size(), 3);
    EXPECT_EQ(reports[1].client_id, 1);
    EXPECT_EQ(reports[1].exec_type, static_cast<uint8_t>(ExecType::PARTIAL_FILL));
    EXPECT_EQ(reports[1].fill_qty, 60);
    EXPECT_EQ(reports[1].leaves_qty, 40);

    EXPECT_EQ(reports[2].client_id, 2);
    EXPECT_EQ(reports[2].exec_type, static_cast<uint8_t>(ExecType::FILL));
    EXPECT_EQ(reports[2].fill_qty, 60);
    EXPECT_EQ(reports[2].leaves_qty, 0);

    EXPECT_TRUE(engine.check_invariants());
}

TEST(OrderBookMatchingTest, IOCImmediateOrCancel) {
    std::vector<ExecutionReportPayload> reports;
    MatchingEngine engine(Symbol("AAPL"), [&](const ExecutionReportPayload& r) {
        reports.push_back(r);
    });

    // Maker: Sell 50 @ 180.00
    engine.process_new_order(1, 1, Side::SELL, OrderType::LIMIT, Price::from_double(180.0), 50, 1000);

    // Taker: IOC Buy 100 @ 180.00 (Fills 50, remaining 50 canceled)
    engine.process_new_order(2, 2, Side::BUY, OrderType::IOC, Price::from_double(180.0), 100, 2000);

    // Reports:
    // 0: Maker NEW
    // 1: Maker FILL 50
    // 2: Taker PARTIAL_FILL 50
    // 3: Taker CANCELED 50 leaves
    ASSERT_EQ(reports.size(), 4);
    EXPECT_EQ(reports[3].client_id, 2);
    EXPECT_EQ(reports[3].exec_type, static_cast<uint8_t>(ExecType::CANCELED));
    EXPECT_EQ(reports[3].leaves_qty, 50);

    EXPECT_TRUE(engine.book().bids().empty());
    EXPECT_TRUE(engine.book().asks().empty());
}

TEST(OrderBookMatchingTest, CancelOrder) {
    std::vector<ExecutionReportPayload> reports;
    MatchingEngine engine(Symbol("MSFT"), [&](const ExecutionReportPayload& r) {
        reports.push_back(r);
    });

    engine.process_new_order(1, 999, Side::BUY, OrderType::LIMIT, Price::from_double(400.0), 100, 1000);
    ASSERT_EQ(reports.size(), 1);
    uint64_t engine_order_id = reports[0].engine_order_id;

    bool canceled = engine.cancel_order(1, 999, engine_order_id, 2000);
    EXPECT_TRUE(canceled);
    ASSERT_EQ(reports.size(), 2);
    EXPECT_EQ(reports[1].exec_type, static_cast<uint8_t>(ExecType::CANCELED));
    EXPECT_TRUE(engine.book().bids().empty());
}
