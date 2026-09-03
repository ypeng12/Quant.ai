#include <gtest/gtest.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <thread>
#include <atomic>
#include "../include/gateway/io_reactor.hpp"
#include "../include/gateway/tcp_order_gateway.hpp"

using namespace quant::gateway;
using namespace quant::protocol;
using namespace quant::core;

TEST(NetworkGatewayTest, TCPOrderSubmissionAndExecution) {
    IOReactor reactor;
    constexpr uint16_t PORT = 19876;
    TCPOrderGateway gateway(reactor, PORT);

    std::atomic<bool> order_received{false};
    NewOrderSinglePayload captured_order{};

    gateway.set_callbacks(
        [&](const NewOrderSinglePayload& ord, uint64_t, uint64_t) {
            captured_order = ord;
            order_received.store(true, std::memory_order_release);
        },
        nullptr
    );

    ASSERT_TRUE(gateway.start());

    // Connect client socket
    int client_fd = socket(AF_INET, SOCK_STREAM, 0);
    ASSERT_GE(client_fd, 0);

    sockaddr_in saddr{};
    saddr.sin_family = AF_INET;
    saddr.sin_addr.s_addr = inet_addr("127.0.0.1");
    saddr.sin_port = htons(PORT);

    int conn = connect(client_fd, reinterpret_cast<sockaddr*>(&saddr), sizeof(saddr));
    ASSERT_EQ(conn, 0);

    // Poll reactor so accept is handled
    reactor.poll_events(50);
    EXPECT_EQ(gateway.connected_clients_count(), 1);

    // Client serializes and sends NewOrderSingle
    NewOrderSinglePayload send_order{
        1, 8888, Symbol("AAPL"),
        static_cast<uint8_t>(Side::BUY),
        static_cast<uint8_t>(OrderType::LIMIT),
        1900000, 50
    };

    std::array<uint8_t, MAX_FRAME_SIZE> frame;
    size_t len = BinaryProtocol::serialize_message(
        std::span<uint8_t>(frame),
        MessageType::NEW_ORDER_SINGLE,
        1, 1000, send_order
    );

    ssize_t sent = send(client_fd, frame.data(), len, 0);
    ASSERT_EQ(sent, static_cast<ssize_t>(len));

    // Reactor polls and processes incoming message
    for (int i = 0; i < 10 && !order_received.load(std::memory_order_acquire); ++i) {
        reactor.poll_events(50);
    }

    EXPECT_TRUE(order_received.load());
    EXPECT_EQ(captured_order.client_id, 1);
    EXPECT_EQ(captured_order.client_order_id, 8888);
    EXPECT_EQ(captured_order.symbol.view(), "AAPL");
    EXPECT_EQ(captured_order.price_raw, 1900000);
    EXPECT_EQ(captured_order.qty, 50);

    // Gateway sends ExecutionReport back to client
    ExecutionReportPayload exec_rep{
        1, 8888, 10001, 1,
        static_cast<uint8_t>(ExecType::NEW),
        1900000, 0, 50, 0
    };
    EXPECT_TRUE(gateway.send_execution_report(exec_rep, 2));

    // Read execution report from client socket
    std::array<uint8_t, MAX_FRAME_SIZE> rx_buf;
    ssize_t n = recv(client_fd, rx_buf.data(), rx_buf.size(), 0);
    ASSERT_GT(n, 0);

    auto hdr = BinaryProtocol::parse_header(std::span<const uint8_t>(rx_buf.data(), n));
    ASSERT_TRUE(hdr.has_value());
    EXPECT_EQ(hdr->msg_type, static_cast<uint8_t>(MessageType::EXECUTION_REPORT));

    close(client_fd);
    gateway.stop();
}
