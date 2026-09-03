#include <gtest/gtest.h>
#include "../include/engine/replay_engine.hpp"
#include <cstdio>

using namespace quant::core;
using namespace quant::order_book;
using namespace quant::protocol;
using namespace quant::engine;

TEST(DeterministicReplayTest, RecordAndReplayInvariants) {
    const std::string journal_file = "/tmp/test_audit_replay.jnl";
    std::remove(journal_file.c_str());

    // 1. Live Run: Record events into Journal
    {
        JournalRecorder recorder(journal_file);
        ASSERT_TRUE(recorder.open());

        NewOrderSinglePayload ord1{1, 101, Symbol("NVDA"), static_cast<uint8_t>(Side::SELL), static_cast<uint8_t>(OrderType::LIMIT), 1200000, 100};
        NewOrderSinglePayload ord2{2, 201, Symbol("NVDA"), static_cast<uint8_t>(Side::SELL), static_cast<uint8_t>(OrderType::LIMIT), 1250000, 200};
        NewOrderSinglePayload ord3{3, 301, Symbol("NVDA"), static_cast<uint8_t>(Side::BUY),  static_cast<uint8_t>(OrderType::LIMIT), 1200000, 50}; // Matches ord1 for 50

        recorder.record_event(MessageType::NEW_ORDER_SINGLE, 1, 1000, ord1);
        recorder.record_event(MessageType::NEW_ORDER_SINGLE, 2, 2000, ord2);
        recorder.record_event(MessageType::NEW_ORDER_SINGLE, 3, 3000, ord3);
        recorder.close();
    }

    // 2. Replay Run: Deterministically replay into a fresh engine instance
    {
        ReplayEngine replay_engine(journal_file);
        MatchingEngine fresh_engine(Symbol("NVDA"));

        bool ok = replay_engine.replay_into_engine(fresh_engine);
        ASSERT_TRUE(ok);
        EXPECT_EQ(replay_engine.replayed_count(), 3);

        // Verification: Exactly 1 trade executed for 50 shares
        EXPECT_EQ(fresh_engine.total_trades(), 1);
        EXPECT_EQ(fresh_engine.total_volume(), 50);

        // Best ask should still be 120.00 with 50 leaves remaining
        auto ba = fresh_engine.book().best_ask();
        ASSERT_TRUE(ba.has_value());
        EXPECT_EQ(ba->raw(), 1200000);

        EXPECT_TRUE(fresh_engine.check_invariants());
    }

    std::remove(journal_file.c_str());
}
