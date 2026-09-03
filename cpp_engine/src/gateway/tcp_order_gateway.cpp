#include "../../include/gateway/tcp_order_gateway.hpp"
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <iostream>

namespace quant::gateway {

static bool make_socket_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) return false;
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

static bool tune_hft_tcp_socket(int fd) {
    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#if defined(SO_REUSEPORT)
    setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &opt, sizeof(opt));
#endif
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

    int buf_size = 4 * 1024 * 1024; // 4MB socket buffer
    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &buf_size, sizeof(buf_size));
    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &buf_size, sizeof(buf_size));

    return make_socket_nonblocking(fd);
}

TCPOrderGateway::TCPOrderGateway(IOReactor& reactor, uint16_t port)
    : reactor_(reactor), port_(port) {}

TCPOrderGateway::~TCPOrderGateway() {
    stop();
}

bool TCPOrderGateway::start() {
    listen_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd_ < 0) {
        return false;
    }

    if (!tune_hft_tcp_socket(listen_fd_)) {
        close(listen_fd_);
        listen_fd_ = -1;
        return false;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port_);

    if (bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(listen_fd_);
        listen_fd_ = -1;
        return false;
    }

    if (listen(listen_fd_, 1024) < 0) {
        close(listen_fd_);
        listen_fd_ = -1;
        return false;
    }

    return reactor_.add_socket(
        listen_fd_,
        IOEvent::READ,
        [this](int fd, IOEvent ev) { handle_listen_event(fd, ev); }
    );
}

void TCPOrderGateway::stop() {
    if (listen_fd_ >= 0) {
        reactor_.remove_socket(listen_fd_);
        close(listen_fd_);
        listen_fd_ = -1;
    }

    auto client_fds = std::move(sessions_);
    for (auto& [fd, session] : client_fds) {
        reactor_.remove_socket(fd);
        close(fd);
    }
    sessions_.clear();
    client_to_fd_.clear();
}

void TCPOrderGateway::handle_listen_event(int fd, IOEvent events) {
    if (!(events & IOEvent::READ)) return;

    for (;;) {
        sockaddr_in client_addr{};
        socklen_t addr_len = sizeof(client_addr);
        int client_fd = accept(fd, reinterpret_cast<sockaddr*>(&client_addr), &addr_len);
        if (client_fd < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                break; // Drained all incoming connections
            }
            break;
        }

        tune_hft_tcp_socket(client_fd);

        ClientSession session;
        session.fd = client_fd;
        session.last_heartbeat_ns = core::TimeUtils::now_ns();
        sessions_[client_fd] = std::move(session);

        reactor_.add_socket(
            client_fd,
            IOEvent::READ,
            [this](int cfd, IOEvent cev) { handle_client_event(cfd, cev); }
        );
    }
}

void TCPOrderGateway::handle_client_event(int fd, IOEvent events) {
    auto it = sessions_.find(fd);
    if (it == sessions_.end()) return;

    ClientSession& session = it->second;

    if (events & (IOEvent::HANGUP | IOEvent::ERROR)) {
        close_client(fd);
        return;
    }

    if (events & IOEvent::READ) {
        std::array<uint8_t, 4096> read_chunk;
        for (;;) {
            ssize_t n = recv(fd, read_chunk.data(), read_chunk.size(), 0);
            if (n > 0) {
                session.rx_buffer.insert(session.rx_buffer.end(), read_chunk.begin(), read_chunk.begin() + n);
            } else if (n == 0) {
                close_client(fd);
                return;
            } else {
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    break;
                }
                close_client(fd);
                return;
            }
        }
        process_client_rx(session);
    }

    if (events & IOEvent::WRITE) {
        flush_client_tx(session);
    }
}

void TCPOrderGateway::process_client_rx(ClientSession& session) {
    size_t offset = 0;
    while (session.rx_buffer.size() - offset >= sizeof(protocol::FrameHeader)) {
        std::span<const uint8_t> remaining(session.rx_buffer.data() + offset, session.rx_buffer.size() - offset);
        auto hdr_opt = protocol::BinaryProtocol::parse_header(remaining);
        if (!hdr_opt) {
            // Corrupt or desynchronized stream, discard 1 byte and realign
            ++offset;
            continue;
        }

        const auto& hdr = *hdr_opt;
        size_t total_msg_size = sizeof(protocol::FrameHeader) + hdr.body_len;
        if (remaining.size() < total_msg_size) {
            // Need more data from socket
            break;
        }

        session.last_heartbeat_ns = core::TimeUtils::now_ns();
        auto msg_type = static_cast<protocol::MessageType>(hdr.msg_type);

        switch (msg_type) {
            case protocol::MessageType::NEW_ORDER_SINGLE: {
                const auto* payload = protocol::BinaryProtocol::parse_payload<protocol::NewOrderSinglePayload>(remaining);
                if (payload) {
                    session.client_id = payload->client_id;
                    client_to_fd_[payload->client_id] = session.fd;
                    if (on_new_order_) {
                        on_new_order_(*payload, hdr.seq_num, hdr.timestamp_ns);
                    }
                }
                break;
            }
            case protocol::MessageType::ORDER_CANCEL_REQ: {
                const auto* payload = protocol::BinaryProtocol::parse_payload<protocol::OrderCancelReqPayload>(remaining);
                if (payload) {
                    session.client_id = payload->client_id;
                    client_to_fd_[payload->client_id] = session.fd;
                    if (on_cancel_) {
                        on_cancel_(*payload, hdr.seq_num, hdr.timestamp_ns);
                    }
                }
                break;
            }
            case protocol::MessageType::HEARTBEAT: {
                // Pong heartbeat back
                protocol::HeartbeatPayload pong{core::TimeUtils::now_ns()};
                std::array<uint8_t, protocol::MAX_FRAME_SIZE> frame;
                size_t len = protocol::BinaryProtocol::serialize_message(
                    std::span<uint8_t>(frame),
                    protocol::MessageType::HEARTBEAT,
                    hdr.seq_num,
                    core::TimeUtils::now_ns(),
                    pong
                );
                if (len > 0) {
                    send_raw(session, frame.data(), len);
                }
                break;
            }
            default:
                break;
        }

        offset += total_msg_size;
    }

    if (offset > 0) {
        session.rx_buffer.erase(session.rx_buffer.begin(), session.rx_buffer.begin() + offset);
    }
}

bool TCPOrderGateway::send_execution_report(const protocol::ExecutionReportPayload& report, uint64_t seq_num) {
    auto it = client_to_fd_.find(report.client_id);
    if (it == client_to_fd_.end()) return false;

    auto sess_it = sessions_.find(it->second);
    if (sess_it == sessions_.end()) return false;

    std::array<uint8_t, protocol::MAX_FRAME_SIZE> frame;
    size_t len = protocol::BinaryProtocol::serialize_message(
        std::span<uint8_t>(frame),
        protocol::MessageType::EXECUTION_REPORT,
        seq_num,
        core::TimeUtils::now_ns(),
        report
    );
    if (len == 0) return false;

    return send_raw(sess_it->second, frame.data(), len);
}

bool TCPOrderGateway::send_raw(ClientSession& session, const void* data, size_t len) {
    if (session.fd < 0 || len == 0) return false;

    const uint8_t* byte_ptr = static_cast<const uint8_t*>(data);

    // If there's already pending backpressure data, maintain FIFO order in buffer
    if (!session.tx_buffer.empty()) {
        session.tx_buffer.insert(session.tx_buffer.end(), byte_ptr, byte_ptr + len);
        return true;
    }

    ssize_t sent = send(session.fd, data, len, 0);
    if (sent == static_cast<ssize_t>(len)) {
        return true; // Sent completely
    }

    if (sent < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            sent = 0;
        } else {
            close_client(session.fd);
            return false;
        }
    }

    // Queue unsent remainder and arm reactor for WRITE
    session.tx_buffer.insert(session.tx_buffer.end(), byte_ptr + sent, byte_ptr + len);
    reactor_.modify_socket(session.fd, IOEvent::READ | IOEvent::WRITE);
    return true;
}

void TCPOrderGateway::flush_client_tx(ClientSession& session) {
    while (!session.tx_buffer.empty()) {
        ssize_t sent = send(session.fd, session.tx_buffer.data(), session.tx_buffer.size(), 0);
        if (sent > 0) {
            session.tx_buffer.erase(session.tx_buffer.begin(), session.tx_buffer.begin() + sent);
        } else if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            break; // Socket still saturated
        } else {
            close_client(session.fd);
            return;
        }
    }

    // When buffer is drained, remove WRITE event to prevent spinloop
    if (session.tx_buffer.empty()) {
        reactor_.modify_socket(session.fd, IOEvent::READ);
    }
}

void TCPOrderGateway::close_client(int fd) {
    reactor_.remove_socket(fd);
    close(fd);

    auto it = sessions_.find(fd);
    if (it != sessions_.end()) {
        client_to_fd_.erase(it->second.client_id);
        sessions_.erase(it);
    }
}

} // namespace quant::gateway
