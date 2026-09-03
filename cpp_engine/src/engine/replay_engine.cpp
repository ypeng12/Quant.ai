#include "../../include/engine/replay_engine.hpp"
#include "../../include/core/time_utils.hpp"
#include <iostream>

namespace quant::engine {

JournalRecorder::JournalRecorder(const std::string& journal_path)
    : path_(journal_path) {}

JournalRecorder::~JournalRecorder() {
    close();
}

bool JournalRecorder::open() {
    out_file_.open(path_, std::ios::binary | std::ios::trunc);
    if (!out_file_.is_open()) return false;

    JournalHeader hdr;
    hdr.magic = JOURNAL_MAGIC;
    hdr.version = 1;
    hdr.start_time_ns = core::TimeUtils::now_ns();

    out_file_.write(reinterpret_cast<const char*>(&hdr), sizeof(JournalHeader));
    return true;
}

void JournalRecorder::close() {
    if (out_file_.is_open()) {
        flush();
        out_file_.close();
    }
}

ReplayEngine::ReplayEngine(const std::string& journal_path)
    : path_(journal_path) {}

bool ReplayEngine::replay(EventDispatchCallback on_event) {
    std::ifstream in(path_, std::ios::binary);
    if (!in.is_open()) return false;

    JournalHeader hdr;
    in.read(reinterpret_cast<char*>(&hdr), sizeof(JournalHeader));
    if (hdr.magic != JOURNAL_MAGIC) return false;

    replayed_count_ = 0;
    std::vector<uint8_t> payload_buf;

    while (in.peek() != EOF) {
        JournalRecordHeader rec;
        in.read(reinterpret_cast<char*>(&rec), sizeof(JournalRecordHeader));
        if (in.gcount() < static_cast<std::streamsize>(sizeof(JournalRecordHeader))) break;

        if (payload_buf.size() < rec.payload_len) {
            payload_buf.resize(rec.payload_len);
        }

        in.read(reinterpret_cast<char*>(payload_buf.data()), rec.payload_len);
        if (in.gcount() < rec.payload_len) break;

        if (on_event) {
            on_event(
                static_cast<protocol::MessageType>(rec.msg_type),
                rec.seq_num,
                rec.timestamp_ns,
                std::span<const uint8_t>(payload_buf.data(), rec.payload_len)
            );
        }
        ++replayed_count_;
    }

    return true;
}

bool ReplayEngine::replay_into_engine(order_book::MatchingEngine& engine) {
    return replay([&engine](
        protocol::MessageType type,
        uint64_t seq,
        uint64_t ts,
        std::span<const uint8_t> payload
    ) {
        (void)seq;
        switch (type) {
            case protocol::MessageType::NEW_ORDER_SINGLE: {
                if (payload.size() >= sizeof(protocol::NewOrderSinglePayload)) {
                    const auto* p = reinterpret_cast<const protocol::NewOrderSinglePayload*>(payload.data());
                    engine.process_new_order(
                        p->client_id,
                        p->client_order_id,
                        static_cast<core::Side>(p->side),
                        static_cast<core::OrderType>(p->order_type),
                        core::Price::from_raw(p->price_raw),
                        p->qty,
                        ts
                    );
                }
                break;
            }
            case protocol::MessageType::ORDER_CANCEL_REQ: {
                if (payload.size() >= sizeof(protocol::OrderCancelReqPayload)) {
                    const auto* p = reinterpret_cast<const protocol::OrderCancelReqPayload*>(payload.data());
                    engine.cancel_order(
                        p->client_id,
                        p->client_order_id,
                        0,
                        ts
                    );
                }
                break;
            }
            default:
                break;
        }
    });
}

} // namespace quant::engine
