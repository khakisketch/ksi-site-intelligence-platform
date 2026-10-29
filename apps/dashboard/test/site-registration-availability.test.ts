import { describe, expect, it, vi, beforeEach } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";
import {
  getSiteRegistrationAvailability,
  getSiteRegistrationMode,
  resolveSiteRegistrationMode,
} from "@/lib/core-api/permissions";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";
import type { WhoAmIResponse } from "@/lib/core-api/types";

const mocked = vi.hoisted(() => ({ whoAmI: vi.fn() }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocked.whoAmI }));

function principal(overrides: Partial<WhoAmIResponse> = {}): WhoAmIResponse {
  return {
    principalId: "op-1",
    organizationId: "org-1",
    kind: "OPERATOR",
    role: "ADMIN",
    deviceId: null,
    permissions: [],
    ...overrides,
  };
}

beforeEach(() => {
  mocked.whoAmI.mockReset();
});

describe("resolveSiteRegistrationMode (legacy semantics unchanged)", () => {
  it("maps registry identity with SITE_BOOTSTRAP to MAPPED_BOOTSTRAP", () => {
    expect(
      resolveSiteRegistrationMode(
        principal({
          registryScoped: true,
          permissions: ["SITES_WRITE"],
          capabilities: ["SITE_BOOTSTRAP"],
        }),
      ),
    ).toBe("MAPPED_BOOTSTRAP");
  });

  it("fails closed for registry identity without SITE_BOOTSTRAP (no legacy fallback)", () => {
    expect(
      resolveSiteRegistrationMode(
        principal({
          registryScoped: true,
          permissions: ["SITES_WRITE", "MISSIONS_ISSUE"],
          capabilities: [],
        }),
      ),
    ).toBe("DENIED");
  });

  it("maps opaque SITES_WRITE + MISSIONS_ISSUE to LEGACY_SITE_ID", () => {
    expect(
      resolveSiteRegistrationMode(
        principal({ permissions: ["SITES_WRITE", "MISSIONS_ISSUE"] }),
      ),
    ).toBe("LEGACY_SITE_ID");
  });

  it("denies opaque identity without MISSIONS_ISSUE", () => {
    expect(
      resolveSiteRegistrationMode(principal({ permissions: ["SITES_WRITE"] })),
    ).toBe("DENIED");
  });
});

describe("getSiteRegistrationMode (legacy compatibility)", () => {
  it("keeps returning DENIED on whoami failure", async () => {
    mocked.whoAmI.mockRejectedValue(new CoreApiError(500, {}));
    await expect(getSiteRegistrationMode()).resolves.toBe("DENIED");
  });

  it("keeps passing through resolved modes", async () => {
    mocked.whoAmI.mockResolvedValue(
      principal({
        registryScoped: true,
        permissions: ["SITES_WRITE"],
        capabilities: ["SITE_BOOTSTRAP"],
      }),
    );
    await expect(getSiteRegistrationMode()).resolves.toBe("MAPPED_BOOTSTRAP");
  });
});

describe("getSiteRegistrationAvailability", () => {
  it("allows mapped bootstrap with the mode attached", async () => {
    const allowedPrincipal = principal({
      registryScoped: true,
      permissions: ["SITES_WRITE"],
      capabilities: ["SITE_BOOTSTRAP"],
    });
    mocked.whoAmI.mockResolvedValue(allowedPrincipal);
    await expect(getSiteRegistrationAvailability()).resolves.toEqual({
      status: "allowed",
      mode: "MAPPED_BOOTSTRAP",
      accountFingerprint: continuityFingerprint(allowedPrincipal),
    });
  });

  it("allows legacy site id with the mode attached", async () => {
    const allowedPrincipal = principal({ permissions: ["SITES_WRITE", "MISSIONS_ISSUE"] });
    mocked.whoAmI.mockResolvedValue(allowedPrincipal);
    await expect(getSiteRegistrationAvailability()).resolves.toEqual({
      status: "allowed",
      mode: "LEGACY_SITE_ID",
      accountFingerprint: continuityFingerprint(allowedPrincipal),
    });
  });

  it("denies a confirmed permission denial (no legacy fallback)", async () => {
    mocked.whoAmI.mockResolvedValue(
      principal({
        registryScoped: true,
        permissions: ["SITES_WRITE"],
        capabilities: [],
      }),
    );
    await expect(getSiteRegistrationAvailability()).resolves.toEqual({
      status: "denied",
    });
  });

  it.each([401, 403])("maps CoreApiError %s to denied", async (status) => {
    mocked.whoAmI.mockRejectedValue(new CoreApiError(status, {}));
    await expect(getSiteRegistrationAvailability()).resolves.toEqual({
      status: "denied",
    });
  });

  it("maps a missing session to denied (fail-closed, no entry)", async () => {
    mocked.whoAmI.mockRejectedValue(new MissingSessionError());
    await expect(getSiteRegistrationAvailability()).resolves.toEqual({
      status: "denied",
    });
  });

  it.each([500, 502, 503])(
    "maps CoreApiError %s to unavailable, never to a fake denial",
    async (status) => {
      mocked.whoAmI.mockRejectedValue(new CoreApiError(status, {}));
      await expect(getSiteRegistrationAvailability()).resolves.toEqual({
        status: "unavailable",
      });
    },
  );

  it("maps a network failure to unavailable", async () => {
    mocked.whoAmI.mockRejectedValue(new TypeError("fetch failed"));
    await expect(getSiteRegistrationAvailability()).resolves.toEqual({
      status: "unavailable",
    });
  });
});
