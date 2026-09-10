import { describe, expect, it } from "vitest";

import {
  resolveExternalWorkOrderExecutionContext,
  type ExternalPlanningOnlyWorkOrderBinding,
} from "@/lib/core-api/external-reconstruction";

const binding: ExternalPlanningOnlyWorkOrderBinding = {
  contractVersion: "external-planning-only-work-order-binding.v1",
  mode: "EXTERNAL_REOBSERVATION_PLANNING",
  organizationId: "org-1",
  siteId: "site-1",
  sourceWorkOrderId: "source-1",
  successorWorkOrderId: "successor-1",
  approvalId: "approval-1",
  approvedBy: "operator-1",
  approvedAt: "2026-09-09T00:00:00Z",
  proposalId: "proposal-1",
  proposalVersion: 1,
  proposalDigest: "sha256:proposal",
  reportDigest: "sha256:report",
  decisionDigest: "sha256:decision",
  zoneDigest: "sha256:zone",
  evidenceDigests: ["sha256:evidence"],
  targetWorkAreas: [{ workAreaId: "area-1", revision: 1, snapshotDigest: "sha256:area" }],
  temporalPolicy: { schemaVersion: "1.0", maxCaptureSpanSeconds: 3600 },
  acquisitionRunAllowed: false,
  missionIssuanceAllowed: false,
  bindingDigest: "sha256:binding",
};

describe("external successor planning context", () => {
  it("recognizes a Core-verified planning-only successor and never infers it from a name or status", () => {
    expect(resolveExternalWorkOrderExecutionContext({ workOrderId: "successor-1", organizationId: "org-1", siteId: "site-1", cycleNumber: 2, version: 3, executionMode: "EXTERNAL_RECONSTRUCTION" }, {
      workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: "EXTERNAL_RECONSTRUCTION", externalPlanningBinding: binding,
    })).toBe("EXTERNAL_REOBSERVATION_PLANNING");
  });

  it.each([
    { ...binding, acquisitionRunAllowed: true } as unknown as ExternalPlanningOnlyWorkOrderBinding,
    { ...binding, missionIssuanceAllowed: true } as unknown as ExternalPlanningOnlyWorkOrderBinding,
    { ...binding, successorWorkOrderId: "other" },
    { ...binding, contractVersion: "wrong" } as unknown as ExternalPlanningOnlyWorkOrderBinding,
    { ...binding, organizationId: "other-org" },
  ])("fails closed for an incomplete binding %j", (externalPlanningBinding) => {
    expect(resolveExternalWorkOrderExecutionContext({ workOrderId: "successor-1", organizationId: "org-1", siteId: "site-1", cycleNumber: 2, version: 3, executionMode: "EXTERNAL_RECONSTRUCTION" }, {
      workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: "EXTERNAL_RECONSTRUCTION", externalPlanningBinding,
    })).toBe("UNVERIFIED");
  });

  it("preserves managed controls only for an explicit verified null binding", () => {
    expect(resolveExternalWorkOrderExecutionContext({ workOrderId: "successor-1", organizationId: "org-1", siteId: "site-1", cycleNumber: 2, version: 3, executionMode: "MANAGED_ACQUISITION" }, {
      workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 2, workOrderVersion: 3, executionMode: "MANAGED_ACQUISITION", externalPlanningBinding: null,
    })).toBe("MANAGED");
  });

  it("fails closed when Core context crosses the actual work-order version, cycle, or site", () => {
    expect(resolveExternalWorkOrderExecutionContext({ workOrderId: "successor-1", organizationId: "org-1", siteId: "site-1", cycleNumber: 2, version: 3, executionMode: "MANAGED_ACQUISITION" }, {
      workOrderId: "successor-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 3, executionMode: "MANAGED_ACQUISITION", externalPlanningBinding: null,
    })).toBe("UNVERIFIED");
  });

  it("recognizes an initial external registration only when Core echoes its execution mode", () => {
    const order = { workOrderId: "initial-1", organizationId: "org-1", siteId: "site-1", cycleNumber: 1, version: 1, executionMode: "EXTERNAL_RECONSTRUCTION" as const };
    const context = { workOrderId: "initial-1", siteId: "site-1", expectedEpochId: "epoch-1", cycleNumber: 1, workOrderVersion: 1, executionMode: "EXTERNAL_RECONSTRUCTION" as const, externalPlanningBinding: null };
    expect(resolveExternalWorkOrderExecutionContext(order, context)).toBe("EXTERNAL_INGRESS");
    expect(resolveExternalWorkOrderExecutionContext(order, { ...context, executionMode: "MANAGED_ACQUISITION" })).toBe("UNVERIFIED");
  });
});
