#pragma once

#include <atomic>
#include <cstddef>
#include <optional>
#include <utility>
#include <memory>
#include <thread>
#include "cache_line.hpp"

namespace quant::core {

/**
 * Lock-Free Multi-Producer Single-Consumer (MPSC) Bounded Ring Buffer Queue.
 * Based on Dmitry Vyukov's bounded queue algorithm.
 * 
 * Allows multiple concurrent network / gateway client threads to push orders
 * into a single matching engine thread without mutexes.
 */
template <typename T, size_t Capacity = 65536>
class alignas(CACHELINE_SIZE) LockFreeMPSCQueue {
    static_assert(Capacity >= 2, "Capacity must be at least 2");
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be a power of two");

    struct Cell {
        std::atomic<size_t> sequence;
        T data;
    };

public:
    LockFreeMPSCQueue() : tail_(0), head_(0) {
        buffer_ = std::make_unique<Cell[]>(Capacity);
        for (size_t i = 0; i < Capacity; ++i) {
            buffer_[i].sequence.store(i, std::memory_order_relaxed);
        }
    }

    ~LockFreeMPSCQueue() = default;

    LockFreeMPSCQueue(const LockFreeMPSCQueue&) = delete;
    LockFreeMPSCQueue& operator=(const LockFreeMPSCQueue&) = delete;

    /**
     * Push an item into the queue. Safe for multiple concurrent producers.
     */
    template <typename... Args>
    bool emplace(Args&&... args) {
        Cell* cell;
        size_t pos = tail_.load(std::memory_order_relaxed);

        for (;;) {
            cell = &buffer_[pos & MASK];
            size_t seq = cell->sequence.load(std::memory_order_acquire);
            intptr_t diff = static_cast<intptr_t>(seq) - static_cast<intptr_t>(pos);

            if (diff == 0) {
                if (tail_.compare_exchange_weak(pos, pos + 1, std::memory_order_relaxed)) {
                    break;
                }
            } else if (diff < 0) {
                return false; // Queue is full
            } else {
                pos = tail_.load(std::memory_order_relaxed);
            }
        }

        cell->data = T(std::forward<Args>(args)...);
        cell->sequence.store(pos + 1, std::memory_order_release);
        return true;
    }

    bool push(const T& item) { return emplace(item); }
    bool push(T&& item) { return emplace(std::move(item)); }

    /**
     * Pop an item from the queue. Strictly single-consumer.
     */
    bool pop(T& out_item) {
        Cell* cell = &buffer_[head_ & MASK];
        size_t seq = cell->sequence.load(std::memory_order_acquire);
        intptr_t diff = static_cast<intptr_t>(seq) - static_cast<intptr_t>(head_ + 1);

        if (diff == 0) {
            out_item = std::move(cell->data);
            cell->sequence.store(head_ + Capacity, std::memory_order_release);
            ++head_;
            return true;
        }

        return false; // Queue is empty
    }

    std::optional<T> pop() {
        T item;
        if (pop(item)) return item;
        return std::nullopt;
    }

    [[nodiscard]] size_t size() const noexcept {
        size_t t = tail_.load(std::memory_order_relaxed);
        size_t h = head_;
        return (t >= h) ? (t - h) : 0;
    }

    [[nodiscard]] bool empty() const noexcept {
        return size() == 0;
    }

    [[nodiscard]] constexpr size_t capacity() const noexcept {
        return Capacity;
    }

private:
    static constexpr size_t MASK = Capacity - 1;

    // Tail: shared and modified by multiple producers via CAS
    alignas(CACHELINE_SIZE) std::atomic<size_t> tail_;

    // Head: accessed and modified strictly by the single consumer
    alignas(CACHELINE_SIZE) size_t head_;

    std::unique_ptr<Cell[]> buffer_;
};

} // namespace quant::core
