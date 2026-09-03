#pragma once

#include <cstddef>
#include <vector>
#include <memory>
#include <new>
#include <cassert>
#include <utility>
#include "cache_line.hpp"

namespace quant::core {

/**
 * Fixed-capacity, pre-allocated Object Pool (Arena Allocator) for zero-allocation hot paths.
 * Eliminates heap fragmentation and malloc/free jitter in trading engines.
 */
template <typename T, size_t Capacity>
class alignas(CACHELINE_SIZE) ObjectPool {
    static_assert(Capacity > 0, "Capacity must be positive");

    union Node {
        alignas(alignof(T)) char storage[sizeof(T)];
        Node* next_free;
    };

public:
    ObjectPool() : free_head_(nullptr), allocated_count_(0) {
        arena_ = std::make_unique<Node[]>(Capacity);
        reset();
    }

    ~ObjectPool() {
        // Any active objects should ideally be destroyed before pool teardown
    }

    ObjectPool(const ObjectPool&) = delete;
    ObjectPool& operator=(const ObjectPool&) = delete;
    ObjectPool(ObjectPool&&) noexcept = default;
    ObjectPool& operator=(ObjectPool&&) noexcept = default;

    void reset() noexcept {
        for (size_t i = 0; i < Capacity - 1; ++i) {
            arena_[i].next_free = &arena_[i + 1];
        }
        arena_[Capacity - 1].next_free = nullptr;
        free_head_ = &arena_[0];
        allocated_count_ = 0;
    }

    template <typename... Args>
    [[nodiscard]] T* allocate(Args&&... args) {
        if (!free_head_) [[unlikely]] {
            return nullptr; // Pool exhausted
        }

        Node* node = free_head_;
        free_head_ = free_head_->next_free;
        ++allocated_count_;

        T* obj = reinterpret_cast<T*>(node->storage);
        ::new (static_cast<void*>(obj)) T(std::forward<Args>(args)...);
        return obj;
    }

    void deallocate(T* obj) noexcept {
        if (!obj) [[unlikely]] return;

        obj->~T();
        Node* node = reinterpret_cast<Node*>(reinterpret_cast<char*>(obj));
        node->next_free = free_head_;
        free_head_ = node;
        --allocated_count_;
    }

    [[nodiscard]] size_t allocated_count() const noexcept { return allocated_count_; }
    [[nodiscard]] size_t available_count() const noexcept { return Capacity - allocated_count_; }
    [[nodiscard]] constexpr size_t capacity() const noexcept { return Capacity; }

    // RAII Deleter for std::unique_ptr
    struct Deleter {
        ObjectPool* pool{nullptr};
        void operator()(T* ptr) const noexcept {
            if (pool && ptr) {
                pool->deallocate(ptr);
            }
        }
    };

    using Ptr = std::unique_ptr<T, Deleter>;

    template <typename... Args>
    [[nodiscard]] Ptr make_unique(Args&&... args) {
        T* raw = allocate(std::forward<Args>(args)...);
        if (!raw) return Ptr(nullptr, Deleter{this});
        return Ptr(raw, Deleter{this});
    }

private:
    std::unique_ptr<Node[]> arena_;
    Node* free_head_;
    size_t allocated_count_;
};

} // namespace quant::core
