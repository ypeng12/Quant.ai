#include "../../include/protocol/binary_protocol.hpp"

namespace quant::protocol {

std::optional<FrameHeader> BinaryProtocol::parse_header(std::span<const uint8_t> buffer) noexcept {
    if (buffer.size() < sizeof(FrameHeader)) {
        return std::nullopt;
    }

    const auto* hdr = reinterpret_cast<const FrameHeader*>(buffer.data());
    if (hdr->magic != PROTOCOL_MAGIC) {
        return std::nullopt;
    }

    return *hdr;
}

} // namespace quant::protocol
