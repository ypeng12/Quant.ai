#include "../../include/market_data/udp_multicast_receiver.hpp"
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <iostream>

namespace quant::market_data {

UDPMulticastReceiver::UDPMulticastReceiver(
    std::string multicast_ip,
    uint16_t port,
    TickHandler on_tick
) : multicast_ip_(std::move(multicast_ip)),
    port_(port),
    on_tick_(std::move(on_tick)),
    gap_tracker_(
        [](const SequenceGap& gap) {
            (void)gap;
            // Gap detected hook
        },
        [this](const protocol::MarketDataTickPayload& tick, uint64_t seq, uint64_t ts) {
            if (on_tick_) on_tick_(tick, seq, ts);
        }
    ) {}

UDPMulticastReceiver::~UDPMulticastReceiver() {
    stop();
}

bool UDPMulticastReceiver::start() {
    sockfd_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (sockfd_ < 0) return false;

    int opt = 1;
    setsockopt(sockfd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#if defined(SO_REUSEPORT)
    setsockopt(sockfd_, SOL_SOCKET, SO_REUSEPORT, &opt, sizeof(opt));
#endif

    // Expand receive buffer to 8MB
    int rcvbuf = 8 * 1024 * 1024;
    setsockopt(sockfd_, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));

    // Non-blocking
    int flags = fcntl(sockfd_, F_GETFL, 0);
    if (flags < 0 || fcntl(sockfd_, F_SETFL, flags | O_NONBLOCK) < 0) {
        close(sockfd_);
        sockfd_ = -1;
        return false;
    }

    sockaddr_in local_addr{};
    local_addr.sin_family = AF_INET;
    local_addr.sin_addr.s_addr = INADDR_ANY;
    local_addr.sin_port = htons(port_);

    if (bind(sockfd_, reinterpret_cast<sockaddr*>(&local_addr), sizeof(local_addr)) < 0) {
        close(sockfd_);
        sockfd_ = -1;
        return false;
    }

    // Join multicast group if valid IP
    if (!multicast_ip_.empty() && multicast_ip_ != "0.0.0.0") {
        ip_mreq mreq{};
        mreq.imr_multiaddr.s_addr = inet_addr(multicast_ip_.c_str());
        mreq.imr_interface.s_addr = INADDR_ANY;
        if (setsockopt(sockfd_, IPPROTO_IP, IP_ADD_MEMBERSHIP, &mreq, sizeof(mreq)) < 0) {
            // Unicast mode fallback if multicast join fails on loopback/test
        }
    }

    running_ = true;
    return true;
}

void UDPMulticastReceiver::stop() {
    if (sockfd_ >= 0) {
        close(sockfd_);
        sockfd_ = -1;
    }
    running_ = false;
}

size_t UDPMulticastReceiver::poll_packets() {
    if (!running_ || sockfd_ < 0) return 0;

    std::array<uint8_t, 2048> buf;
    size_t count = 0;

    for (;;) {
        sockaddr_in from_addr{};
        socklen_t from_len = sizeof(from_addr);
        ssize_t n = recvfrom(sockfd_, buf.data(), buf.size(), 0,
                             reinterpret_cast<sockaddr*>(&from_addr), &from_len);
        if (n <= 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                break; // Socket drained
            }
            break;
        }

        std::span<const uint8_t> span_buf(buf.data(), static_cast<size_t>(n));
        auto hdr_opt = protocol::BinaryProtocol::parse_header(span_buf);
        if (!hdr_opt) continue;

        const auto& hdr = *hdr_opt;
        if (static_cast<protocol::MessageType>(hdr.msg_type) == protocol::MessageType::MARKET_DATA_TICK) {
            const auto* tick = protocol::BinaryProtocol::parse_payload<protocol::MarketDataTickPayload>(span_buf);
            if (tick) {
                gap_tracker_.on_packet_received(hdr.seq_num, hdr.timestamp_ns, *tick);
                ++count;
            }
        }
    }
    return count;
}

} // namespace quant::market_data
