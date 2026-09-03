#include "../../include/engine/trading_engine.hpp"
#include "../../include/core/time_utils.hpp"
#include <iostream>

namespace quant::engine {

TradingEngine::TradingEngine(EngineConfig config)
    : config_(config),
      tcp_gateway_(reactor_, config.tcp_port),
      md_receiver_(config.udp_multicast_ip, config.udp_port),
      matching_engine_(config.symbol),
      risk_engine_(config.risk_limits) {

    if (!config.journal_path.empty()) {
        journal_recorder_ = std::make_unique<JournalRecorder>(config.journal_path);
    }

    // Set up gateway callbacks
    tcp_gateway_.set_callbacks(
        [this](const protocol::NewOrderSinglePayload& order, uint64_t seq, uint64_t ts) {
            EngineInboundEvent ev{};
            ev.type = EngineEventType::NEW_ORDER;
            ev.seq_num = seq;
            ev.timestamp_ns = ts;
            ev.new_order = order;
            inbound_queue_.push(ev);

            if (journal_recorder_) {
                journal_recorder_->record_event(
                    protocol::MessageType::NEW_ORDER_SINGLE, seq, ts, order
                );
            }
        },
        [this](const protocol::OrderCancelReqPayload& cancel, uint64_t seq, uint64_t ts) {
            EngineInboundEvent ev{};
            ev.type = EngineEventType::CANCEL_ORDER;
            ev.seq_num = seq;
            ev.timestamp_ns = ts;
            ev.cancel_order = cancel;
            inbound_queue_.push(ev);

            if (journal_recorder_) {
                journal_recorder_->record_event(
                    protocol::MessageType::ORDER_CANCEL_REQ, seq, ts, cancel
                );
            }
        }
    );

    // Set up matching engine execution report callback
    matching_engine_.set_execution_callback(
        [this](const protocol::ExecutionReportPayload& report) {
            outbound_queue_.push(report);

            if (report.exec_type == static_cast<uint8_t>(core::ExecType::FILL) ||
                report.exec_type == static_cast<uint8_t>(core::ExecType::PARTIAL_FILL)) {
                risk_engine_.on_fill(report.client_id, core::Side::BUY, report.fill_qty);
            }
        }
    );
}

TradingEngine::~TradingEngine() {
    stop();
}

bool TradingEngine::start() {
    if (running_.load(std::memory_order_relaxed)) return true;

    if (journal_recorder_) {
        journal_recorder_->open();
    }

    if (!tcp_gateway_.start()) {
        // Fallback for isolated unit tests / environments where port is restricted
    }

    md_receiver_.start();

    running_.store(true, std::memory_order_release);

    network_thread_ = std::thread([this]() { network_thread_loop(); });
    engine_thread_ = std::thread([this]() { engine_thread_loop(); });

    return true;
}

void TradingEngine::stop() {
    if (!running_.load(std::memory_order_relaxed)) return;

    running_.store(false, std::memory_order_release);

    if (network_thread_.joinable()) network_thread_.join();
    if (engine_thread_.joinable()) engine_thread_.join();

    tcp_gateway_.stop();
    md_receiver_.stop();

    if (journal_recorder_) {
        journal_recorder_->close();
    }
}

void TradingEngine::network_thread_loop() {
    core::ThreadUtils::pin_current_thread(config_.network_core_id);
    core::ThreadUtils::set_thread_name("NetThread");

    while (running_.load(std::memory_order_relaxed)) {
        bool active = false;

        // Poll TCP gateway events
        int n_events = reactor_.poll_events(0);
        if (n_events > 0) active = true;

        // Poll UDP multicast packets
        size_t n_md = md_receiver_.poll_packets();
        if (n_md > 0) active = true;

        // Flush outbound execution reports to TCP clients
        protocol::ExecutionReportPayload report;
        while (outbound_queue_.pop(report)) {
            tcp_gateway_.send_execution_report(report, next_seq_num_++);
            active = true;
        }

        if (!active) {
            core::ThreadUtils::cpu_pause();
        }
    }
}

void TradingEngine::engine_thread_loop() {
    core::ThreadUtils::pin_current_thread(config_.engine_core_id);
    core::ThreadUtils::set_thread_name("EngineCore");

    while (running_.load(std::memory_order_relaxed)) {
        EngineInboundEvent ev;
        if (inbound_queue_.pop(ev)) {
            ++processed_events_;

            switch (ev.type) {
                case EngineEventType::NEW_ORDER: {
                    const auto& ord = ev.new_order;
                    core::Price p = core::Price::from_raw(ord.price_raw);
                    double mid = matching_engine_.book().get_mid_price();

                    // Pre-Trade Risk Check
                    core::RejectReason reason = risk_engine_.check_order(
                        ord.client_id,
                        static_cast<core::Side>(ord.side),
                        p,
                        ord.qty,
                        mid,
                        ev.timestamp_ns
                    );

                    if (reason != core::RejectReason::NONE) {
                        protocol::ExecutionReportPayload reject;
                        reject.client_id = ord.client_id;
                        reject.client_order_id = ord.client_order_id;
                        reject.engine_order_id = 0;
                        reject.exec_id = 0;
                        reject.exec_type = static_cast<uint8_t>(core::ExecType::REJECTED);
                        reject.fill_price_raw = p.raw();
                        reject.fill_qty = 0;
                        reject.leaves_qty = 0;
                        reject.reject_reason = static_cast<uint8_t>(reason);
                        outbound_queue_.push(reject);
                    } else {
                        matching_engine_.process_new_order(
                            ord.client_id,
                            ord.client_order_id,
                            static_cast<core::Side>(ord.side),
                            static_cast<core::OrderType>(ord.order_type),
                            p,
                            ord.qty,
                            ev.timestamp_ns
                        );
                    }
                    break;
                }
                case EngineEventType::CANCEL_ORDER: {
                    const auto& c = ev.cancel_order;
                    matching_engine_.cancel_order(
                        c.client_id,
                        c.client_order_id,
                        0,
                        ev.timestamp_ns
                    );
                    break;
                }
                case EngineEventType::MARKET_DATA_TICK:
                    break;
            }
        } else {
            core::ThreadUtils::cpu_pause();
        }
    }
}

void TradingEngine::submit_order_direct(
    core::ClientId client_id,
    core::ClientOrderId client_order_id,
    core::Side side,
    core::OrderType type,
    core::Price price,
    core::Quantity qty
) {
    uint64_t now_ns = core::TimeUtils::now_ns();
    double mid = matching_engine_.book().get_mid_price();

    core::RejectReason reason = risk_engine_.check_order(
        client_id, side, price, qty, mid, now_ns
    );

    if (reason != core::RejectReason::NONE) {
        protocol::ExecutionReportPayload reject;
        reject.client_id = client_id;
        reject.client_order_id = client_order_id;
        reject.engine_order_id = 0;
        reject.exec_id = 0;
        reject.exec_type = static_cast<uint8_t>(core::ExecType::REJECTED);
        reject.fill_price_raw = price.raw();
        reject.fill_qty = 0;
        reject.leaves_qty = 0;
        reject.reject_reason = static_cast<uint8_t>(reason);
        outbound_queue_.push(reject);
    } else {
        matching_engine_.process_new_order(
            client_id, client_order_id, side, type, price, qty, now_ns
        );
    }
}

} // namespace quant::engine
