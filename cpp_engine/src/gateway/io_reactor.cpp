#include "../../include/gateway/io_reactor.hpp"
#include <unistd.h>
#include <fcntl.h>
#include <unordered_map>
#include <array>
#include <iostream>

#if defined(__linux__)
#include <sys/epoll.h>
#elif defined(__APPLE__)
#include <sys/event.h>
#include <sys/time.h>
#endif

namespace quant::gateway {

struct IOReactor::Impl {
    std::unordered_map<int, EventCallback> callbacks;
    std::unordered_map<int, IOEvent> registered_events;
};

#if defined(__linux__)

IOReactor::IOReactor() : pimpl_(std::make_unique<Impl>()) {
    reactor_fd_ = epoll_create1(EPOLL_CLOEXEC);
}

IOReactor::~IOReactor() {
    if (reactor_fd_ >= 0) {
        close(reactor_fd_);
    }
}

bool IOReactor::add_socket(int fd, IOEvent events, EventCallback callback) {
    if (reactor_fd_ < 0 || fd < 0) return false;

    epoll_event ev{};
    ev.data.fd = fd;
    ev.events = EPOLLET; // Edge-triggered
    if (events & IOEvent::READ) ev.events |= EPOLLIN | EPOLLRDHUP;
    if (events & IOEvent::WRITE) ev.events |= EPOLLOUT;

    if (epoll_ctl(reactor_fd_, EPOLL_CTL_ADD, fd, &ev) < 0) {
        return false;
    }

    pimpl_->callbacks[fd] = std::move(callback);
    pimpl_->registered_events[fd] = events;
    return true;
}

bool IOReactor::modify_socket(int fd, IOEvent events) {
    if (reactor_fd_ < 0 || fd < 0) return false;

    epoll_event ev{};
    ev.data.fd = fd;
    ev.events = EPOLLET;
    if (events & IOEvent::READ) ev.events |= EPOLLIN | EPOLLRDHUP;
    if (events & IOEvent::WRITE) ev.events |= EPOLLOUT;

    if (epoll_ctl(reactor_fd_, EPOLL_CTL_MOD, fd, &ev) < 0) {
        return false;
    }

    pimpl_->registered_events[fd] = events;
    return true;
}

bool IOReactor::remove_socket(int fd) {
    if (reactor_fd_ < 0 || fd < 0) return false;

    epoll_ctl(reactor_fd_, EPOLL_CTL_DEL, fd, nullptr);
    pimpl_->callbacks.erase(fd);
    pimpl_->registered_events.erase(fd);
    return true;
}

int IOReactor::poll_events(int timeout_ms) {
    if (reactor_fd_ < 0 || !running_) return 0;

    constexpr int MAX_EVENTS = 64;
    std::array<epoll_event, MAX_EVENTS> events;

    int nfds = epoll_wait(reactor_fd_, events.data(), MAX_EVENTS, timeout_ms);
    if (nfds <= 0) return nfds;

    for (int i = 0; i < nfds; ++i) {
        int fd = events[i].data.fd;
        auto it = pimpl_->callbacks.find(fd);
        if (it == pimpl_->callbacks.end()) continue;

        IOEvent revents = static_cast<IOEvent>(0);
        if (events[i].events & (EPOLLIN | EPOLLPRI)) revents = revents | IOEvent::READ;
        if (events[i].events & EPOLLOUT) revents = revents | IOEvent::WRITE;
        if (events[i].events & (EPOLLERR)) revents = revents | IOEvent::ERROR;
        if (events[i].events & (EPOLLHUP | EPOLLRDHUP)) revents = revents | IOEvent::HANGUP;

        it->second(fd, revents);
    }
    return nfds;
}

#elif defined(__APPLE__)

IOReactor::IOReactor() : pimpl_(std::make_unique<Impl>()) {
    reactor_fd_ = kqueue();
}

IOReactor::~IOReactor() {
    if (reactor_fd_ >= 0) {
        close(reactor_fd_);
    }
}

bool IOReactor::add_socket(int fd, IOEvent events, EventCallback callback) {
    if (reactor_fd_ < 0 || fd < 0) return false;

    std::array<struct kevent, 2> evs;
    int count = 0;

    if (events & IOEvent::READ) {
        EV_SET(&evs[count++], fd, EVFILT_READ, EV_ADD | EV_CLEAR, 0, 0, nullptr);
    }
    if (events & IOEvent::WRITE) {
        EV_SET(&evs[count++], fd, EVFILT_WRITE, EV_ADD | EV_CLEAR, 0, 0, nullptr);
    }

    if (kevent(reactor_fd_, evs.data(), count, nullptr, 0, nullptr) < 0) {
        return false;
    }

    pimpl_->callbacks[fd] = std::move(callback);
    pimpl_->registered_events[fd] = events;
    return true;
}

bool IOReactor::modify_socket(int fd, IOEvent events) {
    if (reactor_fd_ < 0 || fd < 0) return false;

    // Reset filters
    std::array<struct kevent, 2> evs;
    int count = 0;

    auto cur = pimpl_->registered_events[fd];
    if (cur & IOEvent::READ && !(events & IOEvent::READ)) {
        EV_SET(&evs[count++], fd, EVFILT_READ, EV_DELETE, 0, 0, nullptr);
    } else if (!(cur & IOEvent::READ) && (events & IOEvent::READ)) {
        EV_SET(&evs[count++], fd, EVFILT_READ, EV_ADD | EV_CLEAR, 0, 0, nullptr);
    }

    if (cur & IOEvent::WRITE && !(events & IOEvent::WRITE)) {
        EV_SET(&evs[count++], fd, EVFILT_WRITE, EV_DELETE, 0, 0, nullptr);
    } else if (!(cur & IOEvent::WRITE) && (events & IOEvent::WRITE)) {
        EV_SET(&evs[count++], fd, EVFILT_WRITE, EV_ADD | EV_CLEAR, 0, 0, nullptr);
    }

    if (count > 0) {
        kevent(reactor_fd_, evs.data(), count, nullptr, 0, nullptr);
    }

    pimpl_->registered_events[fd] = events;
    return true;
}

bool IOReactor::remove_socket(int fd) {
    if (reactor_fd_ < 0 || fd < 0) return false;

    std::array<struct kevent, 2> evs;
    int count = 0;
    auto cur = pimpl_->registered_events[fd];
    if (cur & IOEvent::READ) {
        EV_SET(&evs[count++], fd, EVFILT_READ, EV_DELETE, 0, 0, nullptr);
    }
    if (cur & IOEvent::WRITE) {
        EV_SET(&evs[count++], fd, EVFILT_WRITE, EV_DELETE, 0, 0, nullptr);
    }
    if (count > 0) {
        kevent(reactor_fd_, evs.data(), count, nullptr, 0, nullptr);
    }

    pimpl_->callbacks.erase(fd);
    pimpl_->registered_events.erase(fd);
    return true;
}

int IOReactor::poll_events(int timeout_ms) {
    if (reactor_fd_ < 0 || !running_) return 0;

    constexpr int MAX_EVENTS = 64;
    std::array<struct kevent, MAX_EVENTS> events;

    struct timespec ts{};
    struct timespec* timeout_ptr = nullptr;
    if (timeout_ms >= 0) {
        ts.tv_sec = timeout_ms / 1000;
        ts.tv_nsec = (timeout_ms % 1000) * 1000000L;
        timeout_ptr = &ts;
    }

    int nfds = kevent(reactor_fd_, nullptr, 0, events.data(), MAX_EVENTS, timeout_ptr);
    if (nfds <= 0) return nfds;

    for (int i = 0; i < nfds; ++i) {
        int fd = static_cast<int>(events[i].ident);
        auto it = pimpl_->callbacks.find(fd);
        if (it == pimpl_->callbacks.end()) continue;

        IOEvent revents = static_cast<IOEvent>(0);
        if (events[i].filter == EVFILT_READ) revents = revents | IOEvent::READ;
        if (events[i].filter == EVFILT_WRITE) revents = revents | IOEvent::WRITE;
        if (events[i].flags & EV_EOF) revents = revents | IOEvent::HANGUP;
        if (events[i].flags & EV_ERROR) revents = revents | IOEvent::ERROR;

        it->second(fd, revents);
    }
    return nfds;
}

#endif

} // namespace quant::gateway
