#include "ksi/edge/media_control.hpp"

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <utility>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

namespace {

int g_failures = 0;

void Check(bool condition, const char* message) {
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL: %s\n", message);
    }
}

constexpr char kContractDigest[] =
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

std::string MakePrivateDirectory() {
    char pattern[] = "/tmp/ksi-media-control-XXXXXX";
    char* const directory = mkdtemp(pattern);
    if (directory == nullptr || chmod(directory, 0700) != 0) {
        return {};
    }
    return directory;
}

ksi::edge::MediaBaselineRequest Request() {
    ksi::edge::MediaBaselineRequest request;
    request.operator_id = "field-operator";
    request.nonce = "0123456789abcdef0123456789abcdef";
    request.edge_device_id = "edge-m4d-01";
    request.mission_id = "mission-001";
    request.dispatch_id = "dispatch-001";
    request.mission_contract_digest = kContractDigest;
    request.requested_at_utc_ms = 100;
    request.expires_at_utc_ms = 200;
    return request;
}

ksi::edge::MediaBaselineRecord Baseline() {
    ksi::edge::MediaBaselineRecord baseline;
    baseline.request = Request();
    baseline.observed_at_utc_ms = 150;
    baseline.request_digest = ksi::edge::ComputeMediaBaselineRequestDigest(baseline.request);
    baseline.files = {
        {1, "DJI_0001.JPG", 100U},
        {7, "DJI_0007.JPG", 200U},
    };
    return baseline;
}

ksi::edge::NativeActivationSnapshot Activation() {
    ksi::edge::NativeActivationSnapshot activation;
    activation.edge_device_id = "edge-m4d-01";
    activation.mission_id = "mission-001";
    activation.dispatch_id = "dispatch-001";
    activation.context.mission_contract_digest = kContractDigest;
    activation.activated_at_utc_ms = 200;
    return activation;
}

ksi::edge::OperatorMediaOffloadTrigger Trigger(const ksi::edge::MediaBaselineRecord& baseline) {
    ksi::edge::OperatorMediaOffloadTrigger trigger;
    trigger.operator_id = "field-operator";
    trigger.nonce = "fedcba9876543210fedcba9876543210";
    trigger.edge_device_id = "edge-m4d-01";
    trigger.mission_id = "mission-001";
    trigger.dispatch_id = "dispatch-001";
    trigger.mission_contract_digest = kContractDigest;
    trigger.baseline_digest = ksi::edge::ComputeMediaBaselineRecordDigest(baseline);
    trigger.issued_at_utc_ms = 250;
    trigger.expires_at_utc_ms = 350;
    return trigger;
}

void TestControlRoundTripAndBinding() {
    const std::string directory = MakePrivateDirectory();
    Check(!directory.empty(), "create private media-control test directory");
    if (directory.empty()) {
        return;
    }
    const ksi::edge::MediaBaselineRequest request = Request();
    Check(ksi::edge::WriteMediaBaselineRequest(directory, request) ==
              ksi::edge::MediaControlWriteVerdict::kWritten,
          "write a pre-activation baseline request");
    const auto loaded_request = ksi::edge::LoadMediaBaselineRequest(directory, 150);
    Check(loaded_request.verdict == ksi::edge::MediaControlLoadVerdict::kLoaded &&
              loaded_request.request.nonce == request.nonce,
          "load exact owner-only pre-activation request");
    Check(ksi::edge::LoadMediaBaselineRequest(directory, 201).verdict ==
              ksi::edge::MediaControlLoadVerdict::kExpired,
          "expired baseline request cannot be captured later");

    const ksi::edge::MediaBaselineRecord baseline = Baseline();
    Check(ksi::edge::WriteMediaBaselineRecord(directory, baseline) ==
              ksi::edge::MediaControlWriteVerdict::kWritten,
          "write camera baseline only once");
    Check(ksi::edge::WriteMediaBaselineRecord(directory, baseline) ==
              ksi::edge::MediaControlWriteVerdict::kDuplicate,
          "same baseline replay is durable/idempotent");
    const auto loaded_baseline = ksi::edge::LoadMediaBaselineRecord(directory);
    Check(loaded_baseline.verdict == ksi::edge::MediaControlLoadVerdict::kLoaded &&
              loaded_baseline.record.files.size() == 2U,
          "baseline preserves exact source file identities");
    ksi::edge::MediaBaselineRecord reordered = baseline;
    std::swap(reordered.files[0], reordered.files[1]);
    Check(ksi::edge::ComputeMediaBaselineRecordDigest(reordered) ==
              ksi::edge::ComputeMediaBaselineRecordDigest(baseline),
          "baseline canonical digest is independent of vendor list order");

    const ksi::edge::OperatorMediaOffloadTrigger trigger = Trigger(baseline);
    Check(ksi::edge::WriteOperatorMediaOffloadTrigger(directory, trigger) ==
              ksi::edge::MediaControlWriteVerdict::kWritten,
          "write explicit operator one-shot trigger");
    const auto loaded_trigger = ksi::edge::LoadOperatorMediaOffloadTrigger(directory, 300);
    Check(loaded_trigger.verdict == ksi::edge::MediaControlLoadVerdict::kLoaded &&
              loaded_trigger.trigger.baseline_digest == trigger.baseline_digest,
          "load unexpired trigger bound to baseline digest");
    Check(ksi::edge::LoadOperatorMediaOffloadTrigger(directory, 351).verdict ==
              ksi::edge::MediaControlLoadVerdict::kExpired,
          "expired one-shot trigger cannot revive a media run");

    const auto selection = ksi::edge::BuildOperatorMediaSelectionContext(
        Activation(), loaded_baseline.record, loaded_trigger.trigger, 300);
    Check(selection.verdict == ksi::edge::MediaControlSelectionVerdict::kReady &&
              selection.selection_context.trigger_kind ==
                  ksi::edge::MediaOffloadTriggerKind::kOperatorApprovedOneShot &&
              selection.selection_context.baseline_files.size() == 2U,
          "only baseline <= activation <= trigger builds automatic media selection");

    ksi::edge::MediaBaselineRecord replacement = loaded_baseline.record;
    replacement.request.nonce = "00112233445566778899aabbccddeeff";
    replacement.request_digest =
        ksi::edge::ComputeMediaBaselineRequestDigest(replacement.request);
    replacement.observed_at_utc_ms = 160;
    Check(ksi::edge::WriteMediaBaselineRecord(directory, replacement) ==
              ksi::edge::MediaControlWriteVerdict::kReplaced &&
              ksi::edge::LoadMediaBaselineRecord(directory).record.request.nonce == replacement.request.nonce,
          "a new pre-activation request safely replaces only stale control metadata");

    std::error_code error;
    std::filesystem::remove_all(directory, error);
}

void TestControlFailureBoundaries() {
    const ksi::edge::NativeActivationSnapshot activation = Activation();
    ksi::edge::MediaBaselineRecord baseline = Baseline();
    ksi::edge::OperatorMediaOffloadTrigger trigger = Trigger(baseline);

    baseline.request.expires_at_utc_ms = 300;
    baseline.request_digest = ksi::edge::ComputeMediaBaselineRequestDigest(baseline.request);
    baseline.observed_at_utc_ms = 201;
    Check(ksi::edge::BuildOperatorMediaSelectionContext(activation, baseline, trigger, 300).verdict ==
              ksi::edge::MediaControlSelectionVerdict::kBaselineAfterActivation,
          "baseline taken after activation is rejected even with matching IDs");
    baseline = Baseline();
    baseline.request.expires_at_utc_ms = 199;
    baseline.request_digest = ksi::edge::ComputeMediaBaselineRequestDigest(baseline.request);
    trigger = Trigger(baseline);
    Check(ksi::edge::BuildOperatorMediaSelectionContext(activation, baseline, trigger, 300).verdict ==
              ksi::edge::MediaControlSelectionVerdict::kBaselineExpiredBeforeActivation,
          "expired preparation baseline cannot be reused for a later activation");
    baseline = Baseline();
    trigger = Trigger(baseline);
    trigger.issued_at_utc_ms = 199;
    Check(ksi::edge::BuildOperatorMediaSelectionContext(activation, baseline, trigger, 300).verdict ==
              ksi::edge::MediaControlSelectionVerdict::kTriggerBeforeActivation,
          "operator trigger before activation cannot be used");
    trigger = Trigger(baseline);
    trigger.baseline_digest = kContractDigest;
    Check(ksi::edge::BuildOperatorMediaSelectionContext(activation, baseline, trigger, 300).verdict ==
              ksi::edge::MediaControlSelectionVerdict::kBaselineDigestMismatch,
          "forged baseline digest is rejected");
    trigger = Trigger(baseline);
    trigger.mission_id = "mission-other";
    Check(ksi::edge::BuildOperatorMediaSelectionContext(activation, baseline, trigger, 300).verdict ==
              ksi::edge::MediaControlSelectionVerdict::kBindingMismatch,
          "trigger for a different Mission is rejected");
    baseline = Baseline();
    baseline.files.push_back({1, "DJI_DUPLICATE.JPG", 100U});
    Check(ksi::edge::BuildOperatorMediaSelectionContext(activation, baseline, Trigger(Baseline()), 300).verdict ==
              ksi::edge::MediaControlSelectionVerdict::kInvalidBaseline,
          "duplicate camera index in a baseline fails closed");
}

void TestControlPrivateFilesystemGuards() {
    const std::string directory = MakePrivateDirectory();
    Check(!directory.empty(), "create private filesystem-guard directory");
    if (directory.empty()) {
        return;
    }
    const std::filesystem::path request_path =
        std::filesystem::path(directory) / ksi::edge::kMediaBaselineRequestFilename;
    Check(symlink("/etc/passwd", request_path.c_str()) == 0, "place hostile request symlink");
    Check(ksi::edge::LoadMediaBaselineRequest(directory, 150).verdict ==
              ksi::edge::MediaControlLoadVerdict::kUnsafeRecord,
          "symlinked media-control record is never followed");
    (void)unlink(request_path.c_str());

    Check(chmod(directory.c_str(), 0755) == 0, "make control directory group-readable for negative test");
    Check(ksi::edge::WriteMediaBaselineRequest(directory, Request()) ==
              ksi::edge::MediaControlWriteVerdict::kUnsafeStateDirectory,
          "writer rejects non-private state directory");
    Check(chmod(directory.c_str(), 0700) == 0, "restore private control directory");
    Check(ksi::edge::WriteOperatorMediaOffloadTrigger(directory, Trigger(Baseline())) ==
              ksi::edge::MediaControlWriteVerdict::kWritten,
          "write trigger for file-mode negative test");
    const std::filesystem::path trigger_path =
        std::filesystem::path(directory) / ksi::edge::kMediaOperatorTriggerFilename;
    Check(chmod(trigger_path.c_str(), 0644) == 0, "make trigger group-readable for negative test");
    Check(ksi::edge::LoadOperatorMediaOffloadTrigger(directory, 300).verdict ==
              ksi::edge::MediaControlLoadVerdict::kUnsafeRecord,
          "group-readable trigger is rejected rather than parsed");

    std::error_code error;
    std::filesystem::remove_all(directory, error);
}

}  // namespace

int main() {
    TestControlRoundTripAndBinding();
    TestControlFailureBoundaries();
    TestControlPrivateFilesystemGuards();
    if (g_failures != 0) {
        std::fprintf(stderr, "%d media-control contract checks failed\n", g_failures);
    }
    return g_failures == 0 ? 0 : 1;
}
