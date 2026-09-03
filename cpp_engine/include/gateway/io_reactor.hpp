#pragma once

#include <cstdint>
#include <functional>
#include <vector>
#include <memory>
#include "../core/cache_line.hpp"

namespace quant::gateway {

enum class IOEvent : uint8_t {
    READ  = 1 << 0,
    WRITE = 1 << 1,
    ERROR = 1 << 2,
    HANGUP = 1 << 3
};

inline IOEvent operator|(IOEvent a, IOEvent b) {
    return static_cast<IOEvent>(static_cast<uint8_t>(a) | static_cast<uint8_t>(b));
}

inline bool operator&(IOEvent a, IOEvent b) {
    return (static_cast<uint8_t>(a) & static_cast<uint8_t>(b)) != 0;
}

using EventCallback = std::function<void(int fd, IOEvent events)>;

/**
 * Cross-platform Ultra-Low Latency IO Event Demultiplexer.
 * Backends:
 * - Linux: Edge-Triggered epoll (EPOLLET)
 * - macOS: Native kqueue (EVFILT_READ / EVFILT_WRITE)
 */
class alignas(core::CACHELINE_SIZE) IOReactor {
public:
    IOReactor();
    ~IOReactor();

    IOReactor(const IOReactor&) = delete;
    IOReactor& operator=(const IOReactor&) = delete;

    bool add_socket(int fd, IOEvent events, EventCallback callback);
    bool modify_socket(int fd, IOEvent events);
    bool remove_socket(int fd);

    /**
     * Poll ready events and invoke registered callbacks.
     * @param timeout_ms 0 for non-blocking poll, -1 for infinite wait
     * @return Number of events dispatched
     */
    int poll_events(int timeout_ms = 0);

    void stop() noexcept { running_ = false; }
    [[nodiscard]] bool is_running() const noexcept { return running_; }

private:
    int reactor_fd_{-1};
    bool running_{true};
    struct Impl;
    std::unique_ptr<Impl> pimpl_;
};

} // namespace quant::gateway
