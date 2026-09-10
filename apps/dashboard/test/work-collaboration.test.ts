import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ coreFetch: vi.fn() }));
vi.mock("@/lib/core-api/client", () => ({ coreFetch: mocked.coreFetch }));

import {
  createExternalRelativeVolumeReportShare,
  listOrganizationWorkRoster,
  listWorkInbox,
  markWorkInboxItemRead,
  updateOrganizationWorkRosterMember,
} from "@/lib/core-api/work-collaboration";

beforeEach(() => {
  mocked.coreFetch.mockReset();
  mocked.coreFetch.mockResolvedValue({});
});

describe("work collaboration Core client", () => {
  it("uses the pinned organization roster fields and complete-management limit", async () => {
    await listOrganizationWorkRoster({ includeInactive: true, search: "kim" });
    expect(mocked.coreFetch).toHaveBeenCalledWith("/v1/organization-work-roster", {
      query: { includeInactive: "true", search: "kim", limit: 100 },
    });

    await updateOrganizationWorkRosterMember("operator-a", {
      expectedRevision: 3,
      displayName: "현장 담당자",
      roleHint: "FIELD_OPERATOR",
      status: "ACTIVE",
    }, "roster-1");
    expect(mocked.coreFetch).toHaveBeenLastCalledWith("/v1/organization-work-roster/operator-a", {
      method: "PUT",
      body: { expectedRevision: 3, displayName: "현장 담당자", roleHint: "FIELD_OPERATOR", status: "ACTIVE" },
      headers: { "Idempotency-Key": "roster-1" },
    });
  });

  it("keeps inbox target identity typed and does not synthesize a destination URL", async () => {
    await listWorkInbox({ unreadOnly: true, after: "next-1" });
    expect(mocked.coreFetch).toHaveBeenCalledWith("/v1/work-inbox", {
      query: { unreadOnly: "true", after: "next-1", limit: 20 },
    });
    await markWorkInboxItemRead("notice-1", "read-1");
    expect(mocked.coreFetch).toHaveBeenLastCalledWith("/v1/work-inbox/notice-1/read", {
      method: "POST", headers: { "Idempotency-Key": "read-1" },
    });
  });

  it("shares only an exact report reference and recipient principal", async () => {
    await createExternalRelativeVolumeReportShare("report-1", "operator-b", "share-1");
    expect(mocked.coreFetch).toHaveBeenCalledWith("/v1/external-relative-volume-reports/report-1/shares", {
      method: "POST",
      body: { recipientPrincipalId: "operator-b" },
      headers: { "Idempotency-Key": "share-1" },
    });
  });
});
