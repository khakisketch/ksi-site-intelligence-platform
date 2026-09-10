import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  list: vi.fn(),
  inspection: vi.fn(),
}));

vi.mock("@/lib/core-api/external-reconstruction", () => ({
  listExternalReconstructionSubmissions: mocked.list,
  getExternalArtifactInspection: mocked.inspection,
}));

import { resolveExactReportSafeDerivativePair } from "@/lib/core-api/external-report-display";
import type { ExternalRelativeVolumeReportView } from "@/lib/core-api/external-result-workflow";

const digest = (character: string) => `sha256:${character.repeat(64)}`;

function subject(workOrderId: string, submissionId: string, revision = 1) {
  return {
    organizationId: "org-1",
    siteId: "site-1",
    workOrderId,
    submissionId,
    revision,
    submissionDigest: digest(submissionId === "baseline-submission" ? "a" : "b"),
    manifestDigest: digest(submissionId === "baseline-submission" ? "c" : "d"),
  };
}

function inspectionDigest(submissionId: string) {
  return digest(submissionId === "baseline-submission" ? "f" : "e");
}

function reportView(): ExternalRelativeVolumeReportView {
  const baseline = subject("baseline-order", "baseline-submission");
  const current = subject("current-order", "current-submission");
  return {
    request: {
      baseline: { subject: baseline, inspectionReportDigest: inspectionDigest(baseline.submissionId), capturedFrom: "2026-09-01T00:00:00Z", capturedTo: "2026-09-01T00:10:00Z" },
      current: { subject: current, inspectionReportDigest: inspectionDigest(current.submissionId), capturedFrom: "2026-09-02T00:00:00Z", capturedTo: "2026-09-02T00:10:00Z" },
    },
    report: { reportId: `external-relative-volume-report-${"a".repeat(32)}` },
  } as ExternalRelativeVolumeReportView;
}

function revision(source: ReturnType<typeof subject>, submissionRef: string, overrides: Record<string, unknown> = {}) {
  return {
    submissionRef,
    state: "SEALED",
    submission: {
      submissionId: source.submissionId,
      revision: source.revision,
      organizationId: source.organizationId,
      siteId: source.siteId,
      submissionDigest: source.submissionDigest,
    },
    manifest: {
      submissionId: source.submissionId,
      submissionRevision: source.revision,
      submissionDigest: source.submissionDigest,
      organizationId: source.organizationId,
      siteId: source.siteId,
      manifestDigest: source.manifestDigest,
    },
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.inspection.mockImplementation(async (workOrderId: string) => ({
    registrationState: "SEALED",
    sealState: "SEALED",
    inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: { reportDigest: inspectionDigest(workOrderId === "baseline-order" ? "baseline-submission" : "current-submission") } },
    display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-safe-display", receiptDigest: digest("e") },
  }));
});

describe("exact report safe derivative resolver", () => {
  it("uses only an opaque Core-returned revision reference after every retained identity and digest matches", async () => {
    const view = reportView();
    mocked.list.mockImplementation(async (workOrderId: string) => [
      revision(view.request.baseline.subject, `ers-v1-${"a".repeat(64)}`),
      revision(view.request.current.subject, `ers-v1-${"b".repeat(64)}`),
    ].filter((item) => item.submission.submissionId.startsWith(workOrderId === "baseline-order" ? "baseline" : "current")));

    const result = await resolveExactReportSafeDerivativePair(view, { organizationId: "org-1", siteId: "site-1" });

    expect(result).toMatchObject({
      state: "READY",
      baseline: { workOrderId: "baseline-order", submissionRef: `ers-v1-${"a".repeat(64)}` },
      current: { workOrderId: "current-order", submissionRef: `ers-v1-${"b".repeat(64)}` },
    });
    expect(mocked.inspection).toHaveBeenCalledWith("baseline-order", `ers-v1-${"a".repeat(64)}`, 1);
    expect(mocked.inspection).toHaveBeenCalledWith("current-order", `ers-v1-${"b".repeat(64)}`, 1);
  });

  it("fails closed instead of constructing an opaque reference when a returned revision is foreign or stale", async () => {
    const view = reportView();
    mocked.list.mockImplementation(async (workOrderId: string) => workOrderId === "baseline-order"
      ? [revision(view.request.baseline.subject, `ers-v1-${"a".repeat(64)}`, { manifest: { submissionId: "baseline-submission", submissionRevision: 1, submissionDigest: digest("a"), organizationId: "org-1", siteId: "site-1", manifestDigest: digest("f") } })]
      : [revision(view.request.current.subject, `ers-v1-${"b".repeat(64)}`, { submission: { submissionId: "foreign", revision: 1, organizationId: "org-1", siteId: "site-1", submissionDigest: digest("b") } })]);

    const result = await resolveExactReportSafeDerivativePair(view, { organizationId: "org-1", siteId: "site-1" });

    expect(result).toEqual({ state: "UNAVAILABLE", reason: "기준 또는 현재 관측의 보관된 표시 결속을 현재 확인하지 못했습니다." });
    expect(mocked.inspection).not.toHaveBeenCalled();
  });

  it("does not call a reissued safe display report-bound when its retained inspection report differs", async () => {
    const view = reportView();
    mocked.list.mockImplementation(async (workOrderId: string) => [
      revision(workOrderId === "baseline-order" ? view.request.baseline.subject : view.request.current.subject, `ers-v1-${workOrderId === "baseline-order" ? "a".repeat(64) : "b".repeat(64)}`),
    ]);
    mocked.inspection.mockResolvedValue({
      registrationState: "SEALED",
      sealState: "SEALED",
      inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: { reportDigest: digest("0") } },
      display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-reissued", receiptDigest: digest("e") },
    });

    const result = await resolveExactReportSafeDerivativePair(view, { organizationId: "org-1", siteId: "site-1" });

    expect(result).toEqual({ state: "UNAVAILABLE", reason: "기준 또는 현재 관측의 보관된 표시 결속을 현재 확인하지 못했습니다." });
  });
});
