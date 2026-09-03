#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <unordered_map>
#include <functional>
#include <memory>
#include "io_reactor.hpp"
#include "../protocol/binary_protocol.hpp"
#include "../core/time_utils.hpp"

namespace quant::gateway {

struct ClientSession {
    int fd{-1};
    core::ClientId client_id{0};
    std::vector<uint8_t> rx_buffer;
    std::vector<uint8_t> tx_buffer;
    uint64_t last_heartbeat_ns{0};
    bool is_authenticated{false};
};

class alignas(core::CACHELINE_SIZE) TCPOrderGateway {
public:
    using NewOrderCallback = std::function<void(const protocol::NewOrderSinglePayload&, uint64_t seq, uint64_t ts)>;
    using CancelOrderCallback = std::function<void(const protocol::OrderCancelReqPayload&, uint64_t seq, uint64_t ts)>;

    TCPOrderGateway(IOReactor& reactor, uint16_t port);
    ~TCPOrderGateway();

    TCPOrderGateway(const TCPOrderGateway&) = delete;
    TCPOrderGateway& operator=(const TCPOrderGateway&) = delete;

    bool start();
    void stop();

    void set_callbacks(NewOrderCallback on_new_order, CancelOrderCallback on_cancel) {
        on_new_order_ = std::move(on_new_order);
        on_cancel_ = std::move(on_cancel);
    }

    /**
     * Send Execution Report back to client session via TCP.
     * Implements backpressure buffering if socket buffer is saturated.
     */
    bool send_execution_report(const protocol::ExecutionReportPayload& report, uint64_t seq_num);

    /**
     * Broadcast message to all connected clients.
     */
    template <typename PayloadType>
    void broadcast(protocol::MessageType msg_type, uint64_t seq_num, const PayloadType& payload) {
        std::array<uint8_t, protocol::MAX_FRAME_SIZE> frame;
        size_t len = protocol::BinaryProtocol::serialize_message(
            std::span<uint8_t>(frame), msg_type, seq_num, core::TimeUtils::now_ns(), payload
        );
        if (len > 0) {
            for (auto& [fd, session] : sessions_) {
                send_raw(session, frame.data(), len);
            }
        }
    }

    [[nodiscard]] size_t connected_clients_count() const noexcept { return sessions_.size(); }
    [[nodiscard]] uint16_t port() const noexcept { return port_; }

private:
    void handle_listen_event(int fd, IOEvent events);
    void handle_client_event(int fd, IOEvent events);
    void process_client_rx(ClientSession& session);
    void flush_client_tx(ClientSession& session);
    void close_client(int fd);
    bool send_raw(ClientSession& session, const void* data, size_t len);

    IOReactor& reactor_;
    uint16_t port_;
    int listen_fd_{-1};
    std::unordered_map<int, ClientSession> sessions_;
    std::unordered_map<core::ClientId, int> client_to_fd_;

    NewOrderCallback on_new_order_;
    CancelOrderCallback on_cancel_;
};

} // namespace quant::gateway
