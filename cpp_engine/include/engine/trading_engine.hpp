#pragma once

#include <cstdint>
#include <thread>
#include <atomic>
#include <memory>
#include <string>
#include <vector>
#include "../core/types.hpp"
#include "../core/cache_line.hpp"
#include "../core/spsc_queue.hpp"
#include "../core/mpsc_queue.hpp"
#include "../core/thread_utils.hpp"
#include "../protocol/binary_protocol.hpp"
#include "../order_book/matching_engine.hpp"
#include "../risk/risk_engine.hpp"
#include "../gateway/io_reactor.hpp"
#include "../gateway/tcp_order_gateway.hpp"
#include "../market_data/udp_multicast_receiver.hpp"
#include "replay_engine.hpp"

namespace quant::engine {

struct EngineConfig {
    core::Symbol symbol{"AAPL"};
    uint16_t tcp_port{9999};
    std::string udp_multicast_ip{"239.255.0.1"};
    uint16_t udp_port{12345};
    int network_core_id{0};
    int engine_core_id{1};
    std::string journal_path{""};
    risk::RiskLimits risk_limits{};
};

enum class EngineEventType : uint8_t {
    NEW_ORDER = 1,
    CANCEL_ORDER = 2,
    MARKET_DATA_TICK = 3
};

struct EngineInboundEvent {
    EngineEventType type{EngineEventType::NEW_ORDER};
    uint64_t seq_num{0};
    uint64_t timestamp_ns{0};
    union {
        protocol::NewOrderSinglePayload new_order;
        protocol::OrderCancelReqPayload cancel_order;
        protocol::MarketDataTickPayload md_tick;
    };

    EngineInboundEvent() noexcept : type(EngineEventType::NEW_ORDER), seq_num(0), timestamp_ns(0) {
        std::memset(&new_order, 0, sizeof(new_order));
    }
};

class alignas(core::CACHELINE_SIZE) TradingEngine {
public:
    explicit TradingEngine(EngineConfig config = EngineConfig{});
    ~TradingEngine();

    TradingEngine(const TradingEngine&) = delete;
    TradingEngine& operator=(const TradingEngine&) = delete;

    bool start();
    void stop();

    /**
     * Synchronous direct order submission for in-process testing / micro-benchmarks.
     */
    void submit_order_direct(
        core::ClientId client_id,
        core::ClientOrderId client_order_id,
        core::Side side,
        core::OrderType type,
        core::Price price,
        core::Quantity qty
    );

    [[nodiscard]] order_book::MatchingEngine& matching_engine() noexcept { return matching_engine_; }
    [[nodiscard]] const order_book::MatchingEngine& matching_engine() const noexcept { return matching_engine_; }
    [[nodiscard]] risk::RiskEngine& risk_engine() noexcept { return risk_engine_; }
    [[nodiscard]] const risk::RiskEngine& risk_engine() const noexcept { return risk_engine_; }

    [[nodiscard]] uint64_t processed_events_count() const noexcept { return processed_events_; }
    [[nodiscard]] bool is_running() const noexcept { return running_.load(std::memory_order_relaxed); }

private:
    void network_thread_loop();
    void engine_thread_loop();

    EngineConfig config_;
    std::atomic<bool> running_{false};

    // Subsystems
    gateway::IOReactor reactor_;
    gateway::TCPOrderGateway tcp_gateway_;
    market_data::UDPMulticastReceiver md_receiver_;
    order_book::MatchingEngine matching_engine_;
    risk::RiskEngine risk_engine_;
    std::unique_ptr<JournalRecorder> journal_recorder_;

    // Lock-Free IPC Queues between Network Thread & Pinned Engine Thread
    core::LockFreeSPSCQueue<EngineInboundEvent, 65536> inbound_queue_;
    core::LockFreeSPSCQueue<protocol::ExecutionReportPayload, 65536> outbound_queue_;

    // Worker Threads
    std::thread network_thread_;
    std::thread engine_thread_;

    uint64_t processed_events_{0};
    uint64_t next_seq_num_{1};
};

} // namespace quant::engine
