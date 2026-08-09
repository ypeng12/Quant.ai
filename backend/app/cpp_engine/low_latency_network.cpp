// backend/app/cpp_engine/low_latency_network.cpp
/**
 * Test & Benchmark Suite for C++17 Ultra-Low Latency Lock-Free SPSC Network Subsystem.
 */

#include "low_latency_network.hpp"
#include <thread>
#include <chrono>
#include <cassert>

using namespace HFTNet;

void test_lockfree_spsc_queue() {
    std::cout << "[*] Testing LockFreeSPSCQueue (Capacity 1024)..." << std::endl;
    LockFreeSPSCQueue<MarketTickPacket, 1024> queue;

    MarketTickPacket send_pkt{1, 1691500000000000000ULL, {'T','S','L','A'}, 250.50, 100};
    bool pushed = queue.push(send_pkt);
    assert(pushed == true);

    MarketTickPacket recv_pkt{};
    bool popped = queue.pop(recv_pkt);
    assert(popped == true);
    assert(recv_pkt.seq_num == 1);
    assert(recv_pkt.price == 250.50);

    std::cout << "✅ LockFreeSPSCQueue Zero-Mutex Push/Pop Test Passed!" << std::endl;
}

void test_socket_tuning() {
    std::cout << "[*] Testing HFT Socket Optimization Flags..." << std::endl;
    int test_fd = socket(AF_INET, SOCK_DGRAM, 0);
    assert(test_fd >= 0);

    bool tuned = SocketUtils::tune_hft_socket(test_fd, false);
    assert(tuned == true);

    close(test_fd);
    std::cout << "✅ HFT Socket Kernel Tuning (SO_RCVBUF, SO_BUSY_POLL, Non-blocking) Test Passed!" << std::endl;
}

int main() {
    std::cout << "=========================================================================" << std::endl;
    std::cout << "C++17 ULTRA-LOW LATENCY NETWORK SUBSYSTEM & LOCK-FREE SPSC QUEUE" << std::endl;
    std::cout << "=========================================================================" << std::endl;

    test_lockfree_spsc_queue();
    test_socket_tuning();

    std::cout << "=========================================================================" << std::endl;
    std::cout << "[+] All C++ Low-Latency Network Invariants Passed!" << std::endl;
    return 0;
}
