#include <gtest/gtest.h>
#include "../include/protocol/binary_protocol.hpp"

using namespace quant::protocol;
using namespace quant::core;

TEST(BinaryProtocolTest, SerializeAndParseNewOrder) {
    std::array<uint8_t, MAX_FRAME_SIZE> buffer;
    NewOrderSinglePayload order{
        42, 10001, Symbol("AAPL"),
        static_cast<uint8_t>(Side::BUY),
        static_cast<uint8_t>(OrderType::LIMIT),
        1855000, 200
    };

    size_t written = BinaryProtocol::serialize_message(
        std::span<uint8_t>(buffer),
        MessageType::NEW_ORDER_SINGLE,
        1, 1693000000000ULL, order
    );

    ASSERT_GT(written, 0);

    auto hdr = BinaryProtocol::parse_header(std::span<const uint8_t>(buffer.data(), written));
    ASSERT_TRUE(hdr.has_value());
    EXPECT_EQ(hdr->magic, PROTOCOL_MAGIC);
    EXPECT_EQ(hdr->msg_type, static_cast<uint8_t>(MessageType::NEW_ORDER_SINGLE));
    EXPECT_EQ(hdr->seq_num, 1);

    const auto* parsed = BinaryProtocol::parse_payload<NewOrderSinglePayload>(
        std::span<const uint8_t>(buffer.data(), written)
    );
    ASSERT_NE(parsed, nullptr);
    EXPECT_EQ(parsed->client_id, 42);
    EXPECT_EQ(parsed->client_order_id, 10001);
    EXPECT_EQ(parsed->symbol.view(), "AAPL");
    EXPECT_EQ(parsed->price_raw, 1855000);
    EXPECT_EQ(parsed->qty, 200);
}

TEST(BinaryProtocolTest, MalformedBufferHandling) {
    std::array<uint8_t, 10> small_buf{0};
    auto hdr = BinaryProtocol::parse_header(std::span<const uint8_t>(small_buf));
    EXPECT_FALSE(hdr.has_value());

    std::array<uint8_t, sizeof(FrameHeader)> corrupt_hdr{0};
    corrupt_hdr[0] = 0xFF; // Bad magic
    auto bad_hdr = BinaryProtocol::parse_header(std::span<const uint8_t>(corrupt_hdr));
    EXPECT_FALSE(bad_hdr.has_value());
}
