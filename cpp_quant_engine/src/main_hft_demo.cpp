// cpp_quant_engine/src/main_hft_demo.cpp
#include <iostream>
#include <chrono>
#include <thread>
#include "../include/binary_itch_parser.h"
#include "../include/spsc_ring_buffer.h"

struct QuantTick {
    char ticker[8];
    double price;
    uint32_t shares;
    uint64_t timestamp_ns;
};

int main() {
    std::cout << "========================================================\n";
    std::cout << "⚡ Quant.ai C++ Native HFT Binary Engine Benchmark Demo\n";
    std::cout << "========================================================\n";

    // Demo 1: Binary ITCH Struct Parsing Speed Benchmark
    AddOrderMsg raw_msg;
    raw_msg.message_type = 'A';
    raw_msg.stock_locate = 1;
    raw_msg.tracking_num = 101;
    raw_msg.timestamp = 1693248000000000000ULL;
    raw_msg.order_ref_num = 88992211ULL;
    raw_msg.buy_sell_indicator = 'B';
    raw_msg.shares = 500;
    std::memcpy(raw_msg.stock, "TSLA    ", 8);
    raw_msg.price = 3455000; // $345.5000

    const uint8_t* raw_buf = reinterpret_cast<const uint8_t*>(&raw_msg);

    constexpr int ITERATIONS = 1000000; // 1,000,000 parses
    auto start_time = std::chrono::high_resolution_clock::now();

    AddOrderMsg parsed;
    for (int i = 0; i < ITERATIONS; ++i) {
        BinaryITCHParser::parseAddOrder(raw_buf, sizeof(AddOrderMsg), parsed);
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    double total_ms = std::chrono::duration<double, std::milli>(end_time - start_time).count();
    double avg_ns = (total_ms * 1000000.0) / ITERATIONS;

    std::cout << "[+] Binary ITCH Struct Parsing Speed Test:\n";
    std::cout << "    Iterations: " << ITERATIONS << " parses\n";
    std::cout << "    Total Time: " << total_ms << " ms\n";
    std::cout << "    Avg Latency per Parse: " << avg_ns << " nanoseconds (ns) -- Zero JSON Overhead!\n";
    std::cout << "    Decoded Ticker: [" << BinaryITCHParser::decodeTicker(parsed.stock) << "]\n";
    std::cout << "    Decoded Price: $" << BinaryITCHParser::decodePrice(parsed.price) << "\n\n";

    // Demo 2: Lock-Free SPSC RingBuffer Transfer Throughput Benchmark
    SPSCRingBuffer<QuantTick, 65536> ring_buffer;
    QuantTick tick_sample;
    std::memcpy(tick_sample.ticker, "NVDA    ", 8);
    tick_sample.price = 125.80;
    tick_sample.shares = 200;
    tick_sample.timestamp_ns = 1693248000100000000ULL;

    start_time = std::chrono::high_resolution_clock::now();

    int success_pushes = 0;
    for (int i = 0; i < ITERATIONS; ++i) {
        if (ring_buffer.push(tick_sample)) {
            success_pushes++;
        }
        QuantTick popped;
        ring_buffer.pop(popped);
    }

    end_time = std::chrono::high_resolution_clock::now();
    total_ms = std::chrono::duration<double, std::milli>(end_time - start_time).count();
    avg_ns = (total_ms * 1000000.0) / ITERATIONS;

    std::cout << "[+] Lock-Free SPSC RingBuffer IPC Throughput Test:\n";
    std::cout << "    Pushes/Pops: " << success_pushes << " ops\n";
    std::cout << "    Total Time: " << total_ms << " ms\n";
    std::cout << "    Avg Latency per Lock-Free Push+Pop: " << avg_ns << " nanoseconds (ns)\n";
    std::cout << "========================================================\n";

    return 0;
}
