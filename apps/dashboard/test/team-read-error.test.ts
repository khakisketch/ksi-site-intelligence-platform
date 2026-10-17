import { describe, expect, it } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";
import { describeTeamReadError } from "@/app/field/team/team-read-error";

describe("describeTeamReadError", () => {
  it("classifies an expired session without offering a retry", () => {
    const presentation = describeTeamReadError(new CoreApiError(401, {}));
    expect(presentation.message).toContain("세션이 만료");
    expect(presentation.retryable).toBe(false);
    expect(presentation.action).toEqual({ label: "작업으로 돌아가기", href: "/field" });
  });

  it("classifies a permission denial without loosening policy", () => {
    const presentation = describeTeamReadError(new CoreApiError(403, {}));
    expect(presentation.message).toContain("권한");
    expect(presentation.retryable).toBe(false);
    expect(presentation.tone).toBe("high");
    expect(presentation.action.href).toBe("/field");
  });

  it("treats a generic 404 as neutral absence, never as missing configuration", () => {
    const presentation = describeTeamReadError(new CoreApiError(404, {}));
    expect(presentation.message).toContain("확인할 수 없습니다");
    expect(presentation.message).toContain("비었다는 뜻은 아닙니다");
    expect(presentation.message).not.toMatch(/구성|설정|config/i);
    expect(presentation.retryable).toBe(true);
    expect(presentation.tone).toBe("idle");
    expect(presentation.action.href).toBe("/field");
  });

  it.each([500, 502, 503])("retries a transient %s failure", (status) => {
    const presentation = describeTeamReadError(new CoreApiError(status, {}));
    expect(presentation.retryable).toBe(true);
    expect(presentation.action.href).toBe("/field");
  });

  it("respects a server Retry-After hint on an overloaded roster read", () => {
    const presentation = describeTeamReadError(new CoreApiError(503, {}, 30));
    expect(presentation.retryable).toBe(true);
    expect(presentation.retryAfterSeconds).toBe(30);
  });
});
