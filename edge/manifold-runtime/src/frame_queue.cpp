#include "ksi/edge/frame_queue.hpp"

#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace ksi::edge {

const char* ToString(FrameDropReason reason) {
    switch (reason) {
        case FrameDropReason::kAccepted:
            return "ACCEPTED";
        case FrameDropReason::kQueueBusy:
            return "QUEUE_BUSY";
        case FrameDropReason::kQueueFull:
            return "QUEUE_FULL";
        case FrameDropReason::kFrameTooLarge:
            return "FRAME_TOO_LARGE";
        case FrameDropReason::kMalformed:
            return "MALFORMED";
    }
    return "UNKNOWN";
}

BoundedFrameQueue::BoundedFrameQueue(std::size_t slot_count, std::size_t max_frame_bytes)
    : max_frame_bytes_(max_frame_bytes) {
    if (slot_count == 0 || max_frame_bytes == 0) {
        throw std::invalid_argument("frame queue requires non-zero slots and frame bytes");
    }
    slots_.resize(slot_count);
    for (Slot& slot : slots_) {
        slot.storage.resize(max_frame_bytes_);
    }
}

FrameDropReason BoundedFrameQueue::CountDrop(FrameDropReason reason) noexcept {
    switch (reason) {
        case FrameDropReason::kQueueBusy:
            ++queue_busy_;
            break;
        case FrameDropReason::kQueueFull:
            ++stats_.queue_full;
            break;
        case FrameDropReason::kFrameTooLarge:
            ++stats_.frame_too_large;
            break;
        case FrameDropReason::kMalformed:
            ++stats_.malformed;
            break;
        case FrameDropReason::kAccepted:
            ++stats_.accepted;
            break;
    }
    return reason;
}

FrameDropReason BoundedFrameQueue::PushFromCallback(const std::uint8_t* rgb, std::size_t bytes,
                                                     const FrameMetadata& metadata) noexcept {
    if (rgb == nullptr || bytes == 0 || metadata.width == 0 || metadata.height == 0 ||
        metadata.received_monotonic_ns <= 0) {
        // This increments a plain counter without a lock only if try_lock fails below.
        // Callback calls are serialized by the PSDK source in normal operation; the
        // conservative alternative is to drop without claiming accepted data.
        if (mutex_.try_lock()) {
            const FrameDropReason result = CountDrop(FrameDropReason::kMalformed);
            mutex_.unlock();
            return result;
        }
        ++queue_busy_;
        return FrameDropReason::kQueueBusy;
    }
    const std::size_t width = metadata.width;
    const std::size_t height = metadata.height;
    // PSDK's PIXFMT_RGB_PACKED is exactly three tightly packed bytes per
    // pixel.  Accepting a truncated/overlong buffer would make the worker read
    // pixels with a false geometry and can silently poison inference.
    if (width > std::numeric_limits<std::size_t>::max() / height ||
        width * height > std::numeric_limits<std::size_t>::max() / 3U ||
        bytes != width * height * 3U) {
        if (mutex_.try_lock()) {
            const FrameDropReason result = CountDrop(FrameDropReason::kMalformed);
            mutex_.unlock();
            return result;
        }
        ++queue_busy_;
        return FrameDropReason::kQueueBusy;
    }
    if (bytes > max_frame_bytes_) {
        if (mutex_.try_lock()) {
            const FrameDropReason result = CountDrop(FrameDropReason::kFrameTooLarge);
            mutex_.unlock();
            return result;
        }
        ++queue_busy_;
        return FrameDropReason::kQueueBusy;
    }
    if (!mutex_.try_lock()) {
        ++queue_busy_;
        return FrameDropReason::kQueueBusy;
    }
    if (ready_count_ == slots_.size()) {
        const FrameDropReason result = CountDrop(FrameDropReason::kQueueFull);
        mutex_.unlock();
        return result;
    }

    Slot& slot = slots_[write_index_];
    if (slot.ready) {
        // Defensive consistency check; this should be equivalent to full above.
        const FrameDropReason result = CountDrop(FrameDropReason::kQueueFull);
        mutex_.unlock();
        return result;
    }
    std::memcpy(slot.storage.data(), rgb, bytes);
    slot.size = bytes;
    slot.metadata = metadata;
    slot.ready = true;
    write_index_ = (write_index_ + 1U) % slots_.size();
    ++ready_count_;
    const FrameDropReason result = CountDrop(FrameDropReason::kAccepted);
    mutex_.unlock();
    return result;
}

bool BoundedFrameQueue::TryPop(FramePacket* output) {
    if (output == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (ready_count_ == 0) {
        return false;
    }
    Slot& slot = slots_[read_index_];
    if (!slot.ready) {
        return false;
    }
    output->metadata = slot.metadata;
    output->rgb.assign(slot.storage.begin(), slot.storage.begin() + static_cast<std::ptrdiff_t>(slot.size));
    slot.size = 0;
    slot.ready = false;
    read_index_ = (read_index_ + 1U) % slots_.size();
    --ready_count_;
    return true;
}

FrameQueueStats BoundedFrameQueue::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    FrameQueueStats result = stats_;
    result.queue_busy = queue_busy_.load();
    return result;
}

}  // namespace ksi::edge
