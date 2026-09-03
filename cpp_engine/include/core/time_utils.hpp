#pragma once

#include <cstdint>
#include <chrono>
#include <ctime>

namespace quant::core {

class TimeUtils {
public:
    /**
     * Get monotonic time in nanoseconds since boot.
     * Guaranteed strictly monotonic and non-decreasing.
     */
    static inline uint64_t now_ns() noexcept {
#if defined(CLOCK_MONOTONIC_RAW)
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
        return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + static_cast<uint64_t>(ts.tv_nsec);
#else
        auto now = std::chrono::steady_clock::now().time_since_epoch();
        return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
#endif
    }

    /**
     * Get wall clock time in nanoseconds since Unix epoch.
     */
    static inline uint64_t unix_epoch_ns() noexcept {
        auto now = std::chrono::system_clock::now().time_since_epoch();
        return std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
    }

    /**
     * Read CPU timestamp counter (RDTSC on x86_64).
     */
    static inline uint64_t rdtsc() noexcept {
#if defined(__x86_64__) || defined(_M_X64)
        uint32_t hi, lo;
        __asm__ __volatile__ ("rdtsc" : "=a"(lo), "=d"(hi));
        return (static_cast<uint64_t>(hi) << 32) | lo;
#else
        return now_ns();
#endif
    }
};

/**
 * RAII Latency Measurement Utility
 */
template <typename Callback>
class ScopedTimer {
public:
    explicit ScopedTimer(Callback&& cb) : cb_(std::forward<Callback>(cb)), start_ns_(TimeUtils::now_ns()) {}
    ~ScopedTimer() {
        uint64_t elapsed_ns = TimeUtils::now_ns() - start_ns_;
        cb_(elapsed_ns);
    }
private:
    Callback cb_;
    uint64_t start_ns_;
};

} // namespace quant::core
