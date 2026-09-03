#include <gtest/gtest.h>
#include "../include/risk/risk_engine.hpp"

using namespace quant::core;
using namespace quant::risk;

TEST(RiskEngineTest, MaxNotionalRejection) {
    RiskLimits limits;
    limits.max_order_notional = 100'000 * Price::SCALE; // $100k max
    RiskEngine risk(limits);

    // $100 * 500 = $50k -> Pass
    auto r1 = risk.check_order(1, Side::BUY, Price::from_double(100.0), 500, 100.0);
    EXPECT_EQ(r1, RejectReason::NONE);

    // $100 * 2000 = $200k -> Reject
    auto r2 = risk.check_order(1, Side::BUY, Price::from_double(100.0), 2000, 100.0);
    EXPECT_EQ(r2, RejectReason::RISK_NOTIONAL_EXCEEDED);
}

TEST(RiskEngineTest, FatFingerCollarRejection) {
    RiskLimits limits;
    limits.price_collar_pct = 0.05; // 5% max deviation
    RiskEngine risk(limits);

    double mid = 200.0;
    // $205 is 2.5% deviation -> Pass
    auto r1 = risk.check_order(1, Side::BUY, Price::from_double(205.0), 10, mid);
    EXPECT_EQ(r1, RejectReason::NONE);

    // $220 is 10% deviation -> Reject
    auto r2 = risk.check_order(1, Side::BUY, Price::from_double(220.0), 10, mid);
    EXPECT_EQ(r2, RejectReason::RISK_PRICE_COLLAR_VIOLATED);
}

TEST(RiskEngineTest, RateLimiterRejection) {
    RiskLimits limits;
    limits.max_orders_per_sec = 10;
    RiskEngine risk(limits);

    uint64_t now = 1000000000ULL;
    // Consume 10 tokens
    for (int i = 0; i < 10; ++i) {
        EXPECT_EQ(risk.check_order(1, Side::BUY, Price::from_double(100.0), 1, 100.0, now), RejectReason::NONE);
    }

    // 11th order in same second -> Rate limited!
    EXPECT_EQ(risk.check_order(1, Side::BUY, Price::from_double(100.0), 1, 100.0, now),
              RejectReason::RISK_RATE_LIMIT_EXCEEDED);
}

TEST(RiskEngineTest, PositionLimitRejection) {
    RiskLimits limits;
    limits.max_net_position = 500;
    RiskEngine risk(limits);

    risk.on_fill(1, Side::BUY, 400);

    // Another buy 200 exceeds 500 position limit
    EXPECT_EQ(risk.check_order(1, Side::BUY, Price::from_double(100.0), 200, 100.0),
              RejectReason::RISK_POSITION_LIMIT_EXCEEDED);

    // Sell 200 reduces position -> Pass
    EXPECT_EQ(risk.check_order(1, Side::SELL, Price::from_double(100.0), 200, 100.0),
              RejectReason::NONE);
}
