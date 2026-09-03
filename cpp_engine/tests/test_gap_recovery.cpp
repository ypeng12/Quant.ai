#include <gtest/gtest.h>
#include "../include/market_data/gap_recovery.hpp"

using namespace quant::market_data;
using namespace quant::protocol;
using namespace quant::core;

TEST(GapRecoveryTest, SequentialStreamNoGaps) {
    std::vector<uint64_t> received_seqs;
    std::vector<SequenceGap> detected_gaps;

    GapRecoveryTracker tracker(
        [&](const SequenceGap& gap) { detected_gaps.push_back(gap); },
        [&](const MarketDataTickPayload&, uint64_t seq, uint64_t) { received_seqs.push_back(seq); }
    );

    MarketDataTickPayload tick;
    tracker.on_packet_received(1, 1000, tick);
    tracker.on_packet_received(2, 2000, tick);
    tracker.on_packet_received(3, 3000, tick);

    EXPECT_EQ(detected_gaps.size(), 0);
    ASSERT_EQ(received_seqs.size(), 3);
    EXPECT_EQ(received_seqs[0], 1);
    EXPECT_EQ(received_seqs[1], 2);
    EXPECT_EQ(received_seqs[2], 3);
    EXPECT_EQ(tracker.expected_seq(), 4);
}

TEST(GapRecoveryTest, GapDetectionAndBufferedDrain) {
    std::vector<uint64_t> received_seqs;
    std::vector<SequenceGap> detected_gaps;

    GapRecoveryTracker tracker(
        [&](const SequenceGap& gap) { detected_gaps.push_back(gap); },
        [&](const MarketDataTickPayload&, uint64_t seq, uint64_t) { received_seqs.push_back(seq); }
    );

    MarketDataTickPayload tick;
    tracker.on_packet_received(1, 1000, tick);
    // Skip seq 2, packet 3 arrives!
    tracker.on_packet_received(3, 3000, tick);

    ASSERT_EQ(detected_gaps.size(), 1);
    EXPECT_EQ(detected_gaps[0].from_seq, 2);
    EXPECT_EQ(detected_gaps[0].to_seq, 2);
    // Only packet 1 processed so far; packet 3 is buffered waiting for 2
    EXPECT_EQ(received_seqs.size(), 1);
    EXPECT_EQ(tracker.expected_seq(), 2);

    // Now packet 2 arrives via recovery
    tracker.on_gap_packet_recovered(2, 2000, tick);

    // Both 2 and 3 should now be drained in strict sequence!
    ASSERT_EQ(received_seqs.size(), 3);
    EXPECT_EQ(received_seqs[0], 1);
    EXPECT_EQ(received_seqs[1], 2);
    EXPECT_EQ(received_seqs[2], 3);
    EXPECT_EQ(tracker.expected_seq(), 4);
}

TEST(GapRecoveryTest, HistoricalCacheLookup) {
    GapRecoveryTracker tracker;
    MarketDataTickPayload tick;
    tick.bid_price_raw = 1500000;
    tick.bid_qty = 300;

    tracker.store_historical_packet(101, tick);

    auto retrieved = tracker.get_historical_packet(101);
    ASSERT_TRUE(retrieved.has_value());
    EXPECT_EQ(retrieved->bid_price_raw, 1500000);
    EXPECT_EQ(retrieved->bid_qty, 300);

    auto missing = tracker.get_historical_packet(999);
    EXPECT_FALSE(missing.has_value());
}
