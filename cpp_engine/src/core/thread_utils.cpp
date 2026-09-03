#include "../../include/core/thread_utils.hpp"
#include <pthread.h>
#include <unistd.h>
#include <sys/mman.h>
#include <iostream>

#if defined(__APPLE__)
#include <mach/mach.h>
#include <mach/thread_policy.h>
#endif

namespace quant::core {

bool ThreadUtils::pin_current_thread(int core_id) noexcept {
#if defined(__linux__)
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(core_id, &cpuset);
    pthread_t current_thread = pthread_self();
    return pthread_setaffinity_np(current_thread, sizeof(cpu_set_t), &cpuset) == 0;
#elif defined(__APPLE__)
    // On macOS, Darwin does not provide hard core-pinning like Linux pthread_setaffinity_np.
    // Instead, Darwin provides affinity tags via THREAD_AFFINITY_POLICY.
    // Threads sharing an affinity tag will share L2/L3 cache where possible.
    thread_affinity_policy_data_t policy = { core_id };
    mach_port_t mach_thread = pthread_mach_thread_np(pthread_self());
    kern_return_t ret = thread_policy_set(
        mach_thread,
        THREAD_AFFINITY_POLICY,
        reinterpret_cast<thread_policy_t>(&policy),
        THREAD_AFFINITY_POLICY_COUNT
    );
    return ret == KERN_SUCCESS;
#else
    (void)core_id;
    return false;
#endif
}

bool ThreadUtils::set_realtime_priority(int priority) noexcept {
#if defined(__linux__)
    sched_param param{};
    param.sched_priority = priority;
    return pthread_setschedparam(pthread_self(), SCHED_FIFO, &param) == 0;
#elif defined(__APPLE__)
    (void)priority;
    // Mach real-time policy
    mach_port_t mach_thread = pthread_mach_thread_np(pthread_self());
    thread_time_constraint_policy_data_t policy;
    policy.period = 1000000;      // 1ms
    policy.computation = 500000;  // 0.5ms
    policy.constraint = 1000000;  // 1ms
    policy.preemptible = 1;

    kern_return_t ret = thread_policy_set(
        mach_thread,
        THREAD_TIME_CONSTRAINT_POLICY,
        reinterpret_cast<thread_policy_t>(&policy),
        THREAD_TIME_CONSTRAINT_POLICY_COUNT
    );
    return ret == KERN_SUCCESS;
#else
    (void)priority;
    return false;
#endif
}

bool ThreadUtils::set_thread_name(const char* name) noexcept {
#if defined(__linux__)
    return pthread_setname_np(pthread_self(), name) == 0;
#elif defined(__APPLE__)
    return pthread_setname_np(name) == 0;
#else
    (void)name;
    return false;
#endif
}

bool ThreadUtils::lock_all_memory() noexcept {
#if defined(__linux__) || defined(__APPLE__)
    return mlockall(MCL_CURRENT | MCL_FUTURE) == 0;
#else
    return false;
#endif
}

} // namespace quant::core
