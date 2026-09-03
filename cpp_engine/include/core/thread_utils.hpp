#pragma once

#include <cstdint>
#include <string_view>
#include <thread>

namespace quant::core {

class ThreadUtils {
public:
    /**
     * Pin current thread to a dedicated CPU core.
     * Linux: pthread_setaffinity_np
     * macOS: thread_policy_set with THREAD_AFFINITY_POLICY
     */
    static bool pin_current_thread(int core_id) noexcept;

    /**
     * Set thread priority (SCHED_FIFO or max nice).
     */
    static bool set_realtime_priority(int priority = 80) noexcept;

    /**
     * Set thread human-readable name for top / htop / perf.
     */
    static bool set_thread_name(const char* name) noexcept;

    /**
     * Lock all current and future process memory into RAM to prevent paging / page-fault jitter.
     */
    static bool lock_all_memory() noexcept;

    /**
     * Low-latency CPU pause (x86 _mm_pause or ARM isb) to avoid pipeline stalls in spinloops.
     */
    static inline void cpu_pause() noexcept {
#if defined(__x86_64__) || defined(_M_X64)
        __builtin_ia32_pause();
#elif defined(__aarch64__)
        asm volatile("isb" : : : "memory");
#else
        std::this_thread::yield();
#endif
    }
};

} // namespace quant::core
