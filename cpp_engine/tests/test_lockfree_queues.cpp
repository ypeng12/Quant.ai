#include <gtest/gtest.h>
#include <thread>
#include <vector>
#include <atomic>
#include "../include/core/spsc_queue.hpp"
#include "../include/core/mpsc_queue.hpp"
#include "../include/core/thread_utils.hpp"

using namespace quant::core;

TEST(LockFreeQueuesTest, SPSCSingleThreadBasic) {
    LockFreeSPSCQueue<int, 4> queue;
    EXPECT_TRUE(queue.empty());
    EXPECT_EQ(queue.size(), 0);

    EXPECT_TRUE(queue.push(10));
    EXPECT_TRUE(queue.push(20));
    EXPECT_TRUE(queue.push(30));
    EXPECT_TRUE(queue.push(40));
    // Capacity 4 is full: 5th push must return false
    EXPECT_FALSE(queue.push(50));
    EXPECT_EQ(queue.size(), 4);

    int val = 0;
    EXPECT_TRUE(queue.pop(val));
    EXPECT_EQ(val, 10);

    EXPECT_TRUE(queue.push(50));

    EXPECT_TRUE(queue.pop(val));
    EXPECT_EQ(val, 20);
    EXPECT_TRUE(queue.pop(val));
    EXPECT_EQ(val, 30);
    EXPECT_TRUE(queue.pop(val));
    EXPECT_EQ(val, 40);
    EXPECT_TRUE(queue.pop(val));
    EXPECT_EQ(val, 50);

    EXPECT_FALSE(queue.pop(val));
    EXPECT_TRUE(queue.empty());
}

TEST(LockFreeQueuesTest, SPSCConcurrentStress) {
    constexpr size_t TOTAL_ITEMS = 500000;
    LockFreeSPSCQueue<uint64_t, 65536> queue;
    std::vector<uint64_t> received;
    received.reserve(TOTAL_ITEMS);

    std::thread producer([&]() {
        for (uint64_t i = 1; i <= TOTAL_ITEMS; ++i) {
            while (!queue.push(i)) {
                ThreadUtils::cpu_pause();
            }
        }
    });

    std::thread consumer([&]() {
        for (size_t i = 0; i < TOTAL_ITEMS; ++i) {
            uint64_t item;
            while (!queue.pop(item)) {
                ThreadUtils::cpu_pause();
            }
            received.push_back(item);
        }
    });

    producer.join();
    consumer.join();

    ASSERT_EQ(received.size(), TOTAL_ITEMS);
    for (size_t i = 0; i < TOTAL_ITEMS; ++i) {
        ASSERT_EQ(received[i], i + 1);
    }
}

TEST(LockFreeQueuesTest, MPSCConcurrentMultiProducer) {
    constexpr size_t PRODUCERS = 4;
    constexpr size_t PER_PRODUCER = 100000;
    constexpr size_t TOTAL_ITEMS = PRODUCERS * PER_PRODUCER;

    LockFreeMPSCQueue<uint64_t, 65536> queue;
    std::atomic<bool> start_flag{false};
    std::vector<std::thread> producers;

    for (size_t p = 0; p < PRODUCERS; ++p) {
        producers.emplace_back([&, p]() {
            while (!start_flag.load(std::memory_order_acquire)) {}
            for (size_t i = 0; i < PER_PRODUCER; ++i) {
                uint64_t val = (p << 32) | i;
                while (!queue.push(val)) {
                    ThreadUtils::cpu_pause();
                }
            }
        });
    }

    std::vector<uint64_t> received;
    received.reserve(TOTAL_ITEMS);

    std::thread consumer([&]() {
        while (!start_flag.load(std::memory_order_acquire)) {}
        while (received.size() < TOTAL_ITEMS) {
            uint64_t item;
            if (queue.pop(item)) {
                received.push_back(item);
            } else {
                ThreadUtils::cpu_pause();
            }
        }
    });

    start_flag.store(true, std::memory_order_release);

    for (auto& th : producers) th.join();
    consumer.join();

    EXPECT_EQ(received.size(), TOTAL_ITEMS);
}
