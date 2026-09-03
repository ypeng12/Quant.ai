#include <iostream>
#include <csignal>
#include <atomic>
#include <thread>
#include <chrono>
#include "../include/core/thread_utils.hpp"
#include "../include/engine/trading_engine.hpp"

std::atomic<bool> g_stop_requested{false};

void signal_handler(int sig) {
    std::cout << "\n[!] Received signal " << sig << ", initiating deterministic graceful shutdown...\n";
    g_stop_requested.store(true, std::memory_order_release);
}

int main(int argc, char* argv[]) {
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::cout << "========================================================================\n";
    std::cout << "⚡ QUANT.AI PRODUCTION C++20 TRADING ENGINE & EXCHANGE GATEWAY\n";
    std::cout << "   - Cache-aware structs | Lock-Free Queues | Zero-Alloc Object Pool\n";
    std::cout << "   - Epoll/Kqueue IOReactor | Pre-Trade Risk | Deterministic Replay\n";
    std::cout << "========================================================================\n";

    uint16_t tcp_port = 9999;
    uint16_t udp_port = 12345;
    if (argc > 1) tcp_port = static_cast<uint16_t>(std::atoi(argv[1]));
    if (argc > 2) udp_port = static_cast<uint16_t>(std::atoi(argv[2]));

    // Lock process memory to eliminate OS paging page-fault jitter
    quant::core::ThreadUtils::lock_all_memory();

    quant::engine::EngineConfig config;
    config.symbol = quant::core::Symbol("AAPL");
    config.tcp_port = tcp_port;
    config.udp_port = udp_port;
    config.journal_path = "engine_audit.jnl";

    quant::engine::TradingEngine engine(config);
    if (!engine.start()) {
        std::cerr << "[-] Failed to start Trading Engine on ports TCP:" << tcp_port << " UDP:" << udp_port << "\n";
        return 1;
    }

    std::cout << "[+] Trading Engine live and pinned to dedicated worker cores.\n";
    std::cout << "    TCP Order Gateway:  Port " << tcp_port << "\n";
    std::cout << "    UDP Market Feed:    Port " << udp_port << "\n";
    std::cout << "    Deterministic Audit Journal: " << config.journal_path << "\n";
    std::cout << "[+] Engine is actively processing events. Press Ctrl+C to terminate.\n";

    while (!g_stop_requested.load(std::memory_order_relaxed)) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    std::cout << "[*] Draining queues and terminating engine threads...\n";
    engine.stop();
    std::cout << "✅ Deterministic shutdown complete. Audit journal flushed to disk.\n";
    return 0;
}
