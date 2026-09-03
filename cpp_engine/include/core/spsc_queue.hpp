#pragma once

#include <atomic>
#include <cstddef>
#include <optional>
#include <utility>
#include <new>
#include <memory>
#include "cache_line.hpp"

namespace quant::core {

/**
 * Lock-Free Single-Producer Single-Consumer (SPSC) Circular Ring Buffer.
 * Designed for microsecond inter-thread event streaming in High-Frequency Trading.
 * 
 * Features:
 * - Power-of-two bitwise modulo wrapping: index & (Capacity - 1)
 * - Head and Tail stored on isolated 64-byte cache lines to eliminate CPU false sharing
 * - Explicit acquire-release memory order semantics (No locks, zero OS syscalls)
 * - Cache-friendly contiguous ring storage
 */
template <typename T, size_t Capacity = 65536>
class alignas(CACHELINE_SIZE) LockFreeSPSCQueue {
    static_assert(Capacity >= 2, "Capacity must be at least 2");
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be a power of two for bitwise wrapping");

public:
    LockFreeSPSCQueue() : head_(0), cached_tail_(0), tail_(0), cached_head_(0) {
        ring_ = std::make_unique<T[]>(Capacity);
    }

    ~LockFreeSPSCQueue() = default;

    LockFreeSPSCQueue(const LockFreeSPSCQueue&) = delete;
    LockFreeSPSCQueue& operator=(const LockFreeSPSCQueue&) = delete;
    LockFreeSPSCQueue(LockFreeSPSCQueue&&) noexcept = default;
    LockFreeSPSCQueue& operator=(LockFreeSPSCQueue&&) noexcept = default;

    /**
     * Push an item into the queue.
     * Called strictly by the Producer thread.
     */
    template <typename... Args>
    bool emplace(Args&&... args) {
        const size_t current_tail = tail_.load(std::memory_order_relaxed);
        
        // Check against cached head first to avoid cross-core cache invalidation
        if (current_tail - cached_head_ >= Capacity) {
            cached_head_ = head_.load(std::memory_order_acquire);
            if (current_tail - cached_head_ >= Capacity) {
                return false; // Queue full
            }
        }

        ring_[current_tail & MASK] = T(std::forward<Args>(args)...);
        tail_.store(current_tail + 1, std::memory_order_release);
        return true;
    }

    bool push(const T& item) {
        return emplace(item);
    }

    bool push(T&& item) {
        return emplace(std::move(item));
    }

    /**
     * Pop an item from the queue.
     * Called strictly by the Consumer thread.
     */
    bool pop(T& out_item) {
        const size_t current_head = head_.load(std::memory_order_relaxed);

        // Check against cached tail first to reduce atomic loads
        if (current_head == cached_tail_) {
            cached_tail_ = tail_.load(std::memory_order_acquire);
            if (current_head == cached_tail_) {
                return false; // Queue empty
            }
        }

        out_item = std::move(ring_[current_head & MASK]);
        head_.store(current_head + 1, std::memory_order_release);
        return true;
    }

    std::optional<T> pop() {
        T item;
        if (pop(item)) {
            return item;
        }
        return std::nullopt;
    }

    [[nodiscard]] size_t size() const noexcept {
        const size_t t = tail_.load(std::memory_order_relaxed);
        const size_t h = head_.load(std::memory_order_relaxed);
        return (t >= h) ? (t - h) : 0;
    }

    [[nodiscard]] bool empty() const noexcept {
        return head_.load(std::memory_order_relaxed) == tail_.load(std::memory_order_relaxed);
    }

    [[nodiscard]] constexpr size_t capacity() const noexcept {
        return Capacity;
    }

private:
    static constexpr size_t MASK = Capacity - 1;

    // Head line (read/written by consumer)
    alignas(CACHELINE_SIZE) std::atomic<size_t> head_;
    size_t cached_tail_; // Consumer's private shadow copy of tail
    char pad1_[CACHELINE_SIZE - sizeof(std::atomic<size_t>) - sizeof(size_t)];

    // Tail line (read/written by producer)
    alignas(CACHELINE_SIZE) std::atomic<size_t> tail_;
    size_t cached_head_; // Producer's private shadow copy of head
    char pad2_[CACHELINE_SIZE - sizeof(std::atomic<size_t>) - sizeof(size_t)];

    // Storage buffer
    std::unique_ptr<T[]> ring_;
};

} // namespace quant::core
