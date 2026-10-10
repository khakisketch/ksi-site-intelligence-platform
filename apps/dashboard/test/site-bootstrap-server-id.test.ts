import { beforeEach, describe, expect, it, vi } from "vitest";

// F-01 U5: 현장 등록 모드 판정과 두 identity 형태의 전달 계약. 화면(wizard)은
// 이 계약을 소비하는 쪽이고, 여기서는 Build 소유 표면(BFF·client lib)을 고정한다.

const mocked = vi.hoisted(() => {
  class MissingSessionError extends Error {}
  class CoreApiError extends Error {
    status = 500;
    code = "UNKNOWN";
    serverMessage: string | undefined;
    reasonCode: string | undefined;
  }
  return {
    whoami: vi.fn(),
    coreFetch: vi.fn(),
    session: vi.fn(),
    register: vi.fn(),
    MissingSessionError,
    CoreApiError,
  };
});

vi.mock("server-only", () => ({}));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocked.whoami }));
vi.mock("@/lib/core-api/client", () => ({
  coreFetch: mocked.coreFetch,
  CoreApiError: mocked.CoreApiError,
}));
vi.mock("@/lib/core-api/session", () => ({
  getSessionToken: mocked.session,
  MissingSessionError: mocked.MissingSessionError,
}));
vi.mock("@/lib/core-api/sites", () => ({ registerSite: mocked.register }));

import { POST as postSite } from "@/app/api/sites/route";
import {
  getSiteRegistrationMode,
  resolveSiteRegistrationMode,
} from "@/lib/core-api/permissions";
import type { WhoAmIResponse } from "@/lib/core-api/types";

const FRAME = {
  crs: "EPSG:5186",
  verticalDatum: "KNGeoid2018",
  unit: "meter" as const,
  transformVersion: "1.0.0",
};

function principal(overrides: Partial<WhoAmIResponse>): WhoAmIResponse {
  return {
    principalId: "user-1",
    organizationId: "org-1",
    kind: "OPERATOR",
    role: "FIELD_OPERATOR",
    deviceId: null,
    permissions: ["SITES_READ", "SITES_WRITE"],
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("F-01 Site 등록 모드 판정", () => {
  it("mapped + SITE_BOOTSTRAP + SITES_WRITE 는 bootstrap 모드다 — MISSIONS_ISSUE 불요", () => {
    expect(
      resolveSiteRegistrationMode(
        principal({
          registryScoped: true,
          capabilities: ["SITE_BOOTSTRAP"],
          siteScopeLevel: "ORG_ALL",
        }),
      ),
    ).toBe("MAPPED_BOOTSTRAP");
  });

  it("mapped 인데 capability 가 없으면 DENIED — legacy 로 되돌아가지 않는다", () => {
    for (const capabilities of [[], undefined]) {
      expect(
        resolveSiteRegistrationMode(principal({ registryScoped: true, capabilities })),
      ).toBe("DENIED");
    }
  });

  it("mapped + capability 라도 SITES_WRITE 가 없으면 DENIED", () => {
    expect(
      resolveSiteRegistrationMode(
        principal({
          registryScoped: true,
          capabilities: ["SITE_BOOTSTRAP"],
          permissions: ["SITES_READ"],
        }),
      ),
    ).toBe("DENIED");
    // VIEWER + capability 는 Core 도 403 이다 — UI 가 먼저 막는다.
    expect(
      resolveSiteRegistrationMode(
        principal({
          registryScoped: true,
          capabilities: ["SITE_BOOTSTRAP"],
          permissions: ["SITES_READ"],
        }),
      ),
    ).toBe("DENIED");
  });

  it("legacy metadata(구버전 서버)는 기존 계약 그대로다", () => {
    expect(
      resolveSiteRegistrationMode(
        principal({ permissions: ["SITES_READ", "SITES_WRITE", "MISSIONS_ISSUE"] }),
      ),
    ).toBe("LEGACY_SITE_ID");
    // SITES_WRITE 만으로는 부족하다(기존 계약의 AND 유지).
    expect(
      resolveSiteRegistrationMode(principal({ permissions: ["SITES_WRITE"] })),
    ).toBe("DENIED");
    expect(resolveSiteRegistrationMode(principal({}))).toBe("DENIED");
  });

  it("whoami 실패(세션 없음·Core 장애)는 DENIED — 진입을 열지 않는다", async () => {
    mocked.whoami.mockRejectedValue(new Error("no session"));
    await expect(getSiteRegistrationMode()).resolves.toBe("DENIED");
  });

  it("registryScoped=false(명시)는 legacy 판정이다 — metadata 누락 추론과 동일", async () => {
    mocked.whoami.mockResolvedValue(
      principal({
        registryScoped: false,
        siteScopeLevel: "LEGACY",
        permissions: ["SITES_READ", "SITES_WRITE", "MISSIONS_ISSUE"],
      }),
    );
    await expect(getSiteRegistrationMode()).resolves.toBe("LEGACY_SITE_ID");
  });
});

describe("F-01 registerSite identity 형태", () => {
  it("bootstrap 형태는 bootstrapRequestId 만 보낸다(siteId 없음)", async () => {
    const actual = await vi.importActual<typeof import("@/lib/core-api/sites")>(
      "@/lib/core-api/sites",
    );
    mocked.coreFetch.mockResolvedValue({ site: { siteId: "site-9" } });
    const site = await actual.registerSite({
      bootstrapRequestId: "0f8fad5b-d9cb-469f-a165-70867728950e",
      name: "새 현장",
      siteFrame: FRAME,
    });
    expect(site.siteId).toBe("site-9");
    expect(mocked.coreFetch).toHaveBeenCalledWith("/v1/sites", {
      method: "POST",
      body: {
        bootstrapRequestId: "0f8fad5b-d9cb-469f-a165-70867728950e",
        name: "새 현장",
        siteFrame: FRAME,
      },
    });
  });

  it("legacy 형태는 siteId 를 그대로 보낸다", async () => {
    const actual = await vi.importActual<typeof import("@/lib/core-api/sites")>(
      "@/lib/core-api/sites",
    );
    mocked.coreFetch.mockResolvedValue({ site: { siteId: "site-1" } });
    await actual.registerSite({ siteId: "site-1", name: "현장", siteFrame: FRAME });
    const body = mocked.coreFetch.mock.calls[0][1].body;
    expect(body.siteId).toBe("site-1");
    expect(body.bootstrapRequestId).toBeUndefined();
  });
});

describe("F-01 BFF /api/sites", () => {
  function request(value: unknown, headers: Record<string, string> = {}) {
    return new Request("http://console.test/api/sites", {
      method: "POST",
      headers: { host: "console.test", "content-type": "application/json", ...headers },
      body: typeof value === "string" ? value : JSON.stringify(value),
    });
  }

  it("mapped bootstrap body 를 그대로 Core 로 전달하고 201 을 반환한다", async () => {
    mocked.session.mockResolvedValue("token");
    mocked.register.mockResolvedValue({ siteId: "site-9" });
    const body = {
      bootstrapRequestId: "0f8fad5b-d9cb-469f-a165-70867728950e",
      name: "새 현장",
      siteFrame: FRAME,
    };
    const response = await postSite(request(body) as never);
    expect(response.status).toBe(201);
    expect(mocked.register).toHaveBeenCalledWith(body);
  });

  it("세션 검증이 본문 파싱보다 먼저다 — 무인증+깨진 JSON 도 401", async () => {
    mocked.session.mockRejectedValue(new mocked.MissingSessionError());
    const response = await postSite(request("{not json") as never);
    expect(response.status).toBe(401);
    expect(mocked.register).not.toHaveBeenCalled();
  });
});
