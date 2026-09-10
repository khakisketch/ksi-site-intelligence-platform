import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), inspection: vi.fn(), download: vi.fn() }));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/external-reconstruction", () => ({
  getExternalArtifactInspection: mocked.inspection,
  getExternalSanitizedDisplayDownload: mocked.download,
}));

import { GET as inspectionGet } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/inspection/route";
import { GET as downloadGet } from "@/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/display-artifacts/[sanitizedDisplayRef]/download/route";

const inspectionContext = { params: Promise.resolve({ workOrderId: "work-1", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: "1" }) };
const downloadContext = { params: Promise.resolve({ ...awaitableInspectionParams(), sanitizedDisplayRef: "sda-v1-synthetic-display" }) };

function awaitableInspectionParams() {
  return { workOrderId: "work-1", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: "1" };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("session-token");
  mocked.inspection.mockResolvedValue({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-synthetic-display", receiptDigest: `sha256:${"b".repeat(64)}` } });
  mocked.download.mockResolvedValue({ sanitizedDisplayRef: "sda-v1-synthetic-display", receiptDigest: `sha256:${"b".repeat(64)}`, observedDerivativeSha256: `sha256:${"c".repeat(64)}`, observedDerivativeSizeBytes: 12, observedDerivativeContentType: "image/tiff", downloadUrl: "https://storage.example.test/sanitized.tif?opaque", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
});

describe("external inspection read BFF", () => {
  it("forwards only the exact scoped inspection identity after the session check", async () => {
    const response = await inspectionGet(new Request("http://console.test/api") as never, inspectionContext);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ registrationState: "SEALED", display: { sanitizedDisplayRef: "sda-v1-synthetic-display" } });
    expect(mocked.session).toHaveBeenCalledBefore(mocked.inspection);
    expect(mocked.inspection).toHaveBeenCalledWith("work-1", `ers-v1-${"a".repeat(64)}`, 1);
  });

  it("rejects invalid sealed and display references without calling Core", async () => {
    const invalidInspection = { params: Promise.resolve({ workOrderId: "work-1", submissionRef: "raw-submission-id", revision: "0" }) };
    const invalidDisplay = { params: Promise.resolve({ ...awaitableInspectionParams(), sanitizedDisplayRef: "raw.tif" }) };
    expect((await inspectionGet(new Request("http://console.test/api") as never, invalidInspection)).status).toBe(404);
    expect((await downloadGet(new Request("http://console.test/api") as never, invalidDisplay)).status).toBe(404);
    expect(mocked.inspection).not.toHaveBeenCalled();
    expect(mocked.download).not.toHaveBeenCalled();
  });

  it("returns only the Core-issued scoped display capability", async () => {
    const response = await downloadGet(new Request("http://console.test/api") as never, downloadContext);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual(await mocked.download.mock.results[0].value);
    expect(mocked.download).toHaveBeenCalledWith("work-1", `ers-v1-${"a".repeat(64)}`, 1, "sda-v1-synthetic-display");
  });
});
