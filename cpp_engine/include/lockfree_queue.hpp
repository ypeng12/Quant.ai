#ifndef LOCKFREE_QUEUE_HPP
#define LOCKFREE_QUEUE_HPP

#include <atomic>
#include <cstddef>
#include <vector>
#include <optional>
#include <stdexcept>

namespace quant {

/**
 * Lock-Free Single-Producer Single-Consumer (SPSC) RingBuffer Queue.
 * Optimized for microsecond event dispatching in High-Frequency Quant Trading.
 */
template <typename T, size_t Capacity = 1024>
class LockFreeSPSCQueue {
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be a power of two");

public:
    LockFreeSPSCQueue() : head_(0), tail_(0) {
        buffer_.resize(Capacity);
    }

    bool push(const T& item) {
        const size_t current_tail = tail_.load(std::memory_order_relaxed);
        const size_t current_head = head_.load(std::memory_order_acquire);

        if ((current_tail - current_head) >= Capacity) {
            return false; // Queue Full
        }

        buffer_[current_tail & (Capacity - 1)] = item;
        tail_.store(current_tail + 1, std::memory_order_release);
        return true;
    }

    std::optional<T> pop() {
        const size_t current_head = head_.load(std::memory_order_relaxed);
        const size_t current_tail = tail_.load(std::memory_order_acquire);

        if (current_head == current_tail) {
            return std::nullopt; // Queue Empty
        }

        T item = buffer_[current_head & (Capacity - 1)];
        head_.store(current_head + 1, std::memory_order_release);
        return item;
    }

    size_t size() const {
        return tail_.load(std::memory_order_relaxed) - head_.load(std::memory_order_relaxed);
    }

    bool empty() const {
        return size() == 0;
    }

private:
    std::vector<T> buffer_;
    alignas(64) std::atomic<size_t> head_;
    alignas(64) std::atomic<size_t> tail_;
};

} // namespace quant

#endif // LOCKFREE_QUEUE_HPP
