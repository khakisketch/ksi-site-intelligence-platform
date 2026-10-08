// Bounded RGB frame ingress for the Manifold PSDK callback.
//
// The callback may only timestamp, take the try-lock, and memcpy into one of
// these preallocated slots. Inference, image conversion, allocations, file I/O,
// and network work are intentionally absent from PushFromCallback().

#ifndef KSI_EDGE_FRAME_QUEUE_HPP
#define KSI_EDGE_FRAME_QUEUE_HPP

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <vector>

namespace ksi::edge {

using MonotonicNs = std::int64_t;

struct FrameMetadata {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t frame_id = 0;
    MonotonicNs received_monotonic_ns = 0;
    // RGB liveview on Manifold 3 does not currently provide a sensor timestamp.
    // A future source may supply one; 0 means unavailable and must not count as
    // sensor alignment evidence.
    MonotonicNs sensor_timestamp_ns = 0;
    // 0 means realtime UTC was unavailable.  This is separate from monotonic
    // callback ordering and is required by a projector before it may assign an
    // EventBundle/WorldEntity occurrence timestamp.
    std::int64_t received_utc_ms = 0;
};

enum class FrameDropReason {
    kAccepted,
    kQueueBusy,
    kQueueFull,
    kFrameTooLarge,
    kMalformed,
};

const char* ToString(FrameDropReason reason);

struct FramePacket {
    FrameMetadata metadata;
    std::vector<std::uint8_t> rgb;
};

struct FrameQueueStats {
    std::uint64_t accepted = 0;
    std::uint64_t queue_busy = 0;
    std::uint64_t queue_full = 0;
    std::uint64_t frame_too_large = 0;
    std::uint64_t malformed = 0;
};

class BoundedFrameQueue {
public:
    BoundedFrameQueue(std::size_t slot_count, std::size_t max_frame_bytes);

    // PSDK callback entry point: no dynamic allocation, no waiting, no user code.
    FrameDropReason PushFromCallback(const std::uint8_t* rgb, std::size_t bytes,
                                     const FrameMetadata& metadata) noexcept;

    // Worker-side pull. Copying into output is deliberately outside the callback.
    bool TryPop(FramePacket* output);
    FrameQueueStats stats() const;
    std::size_t capacity() const { return slots_.size(); }
    std::size_t max_frame_bytes() const { return max_frame_bytes_; }

private:
    struct Slot {
        std::vector<std::uint8_t> storage;
        std::size_t size = 0;
        FrameMetadata metadata;
        bool ready = false;
    };

    FrameDropReason CountDrop(FrameDropReason reason) noexcept;

    const std::size_t max_frame_bytes_;
    mutable std::mutex mutex_;
    std::vector<Slot> slots_;
    std::size_t write_index_ = 0;
    std::size_t read_index_ = 0;
    std::size_t ready_count_ = 0;
    // A callback that cannot acquire the queue lock must still leave an
    // observable typed drop.  This one counter is atomic because it is the
    // only counter updated without the mutex; all other counters remain under
    // the queue lock together with the state they describe.
    std::atomic<std::uint64_t> queue_busy_{0};
    FrameQueueStats stats_;
};

}  // namespace ksi::edge

#endif  // KSI_EDGE_FRAME_QUEUE_HPP
