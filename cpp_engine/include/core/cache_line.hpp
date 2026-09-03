#pragma once

#include <cstddef>
#include <new>

namespace quant::core {

// Standard x86_64 / ARM64 cache line size (64 bytes)
constexpr size_t CACHELINE_SIZE = 64;

#if defined(__cpp_lib_hardware_interference_size) && __cpp_lib_hardware_interference_size >= 201703L
    constexpr size_t HARDWARE_DESTRUCTIVE_INTERFERENCE_SIZE = std::hardware_destructive_interference_size;
    constexpr size_t HARDWARE_CONSTRUCTIVE_INTERFERENCE_SIZE = std::hardware_constructive_interference_size;
#else
    constexpr size_t HARDWARE_DESTRUCTIVE_INTERFERENCE_SIZE = CACHELINE_SIZE;
    constexpr size_t HARDWARE_CONSTRUCTIVE_INTERFERENCE_SIZE = CACHELINE_SIZE;
#endif

// Padding helper to prevent false sharing between concurrent thread variables
template <size_t Size>
struct CacheLinePad {
    static constexpr size_t pad_bytes = (CACHELINE_SIZE - (Size % CACHELINE_SIZE)) % CACHELINE_SIZE;
    char pad[pad_bytes == 0 ? CACHELINE_SIZE : pad_bytes];
};

} // namespace quant::core
