#pragma once

#include <cstdint>
#include <string>
#include <functional>
#include <span>
#include "../core/types.hpp"
#include "../protocol/binary_protocol.hpp"
#include "gap_recovery.hpp"

namespace quant::market_data {

class UDPMulticastReceiver {
public:
    using TickHandler = std::function<void(const protocol::MarketDataTickPayload&, uint64_t seq, uint64_t ts)>;

    UDPMulticastReceiver(
        std::string multicast_ip,
        uint16_t port,
        TickHandler on_tick = nullptr
    );
    ~UDPMulticastReceiver();

    UDPMulticastReceiver(const UDPMulticastReceiver&) = delete;
    UDPMulticastReceiver& operator=(const UDPMulticastReceiver&) = delete;

    bool start();
    void stop();

    /**
     * Non-blocking drain of UDP socket buffer.
     * @return Number of packets received and parsed.
     */
    size_t poll_packets();

    [[nodiscard]] int socket_fd() const noexcept { return sockfd_; }
    [[nodiscard]] GapRecoveryTracker& gap_tracker() noexcept { return gap_tracker_; }
    [[nodiscard]] const GapRecoveryTracker& gap_tracker() const noexcept { return gap_tracker_; }

private:
    std::string multicast_ip_;
    uint16_t port_;
    int sockfd_{-1};
    bool running_{false};

    TickHandler on_tick_;
    GapRecoveryTracker gap_tracker_;
};

} // namespace quant::market_data
