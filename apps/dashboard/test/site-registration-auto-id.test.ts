import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createGeneratedSiteId,
  createRegistrationUuid,
} from "@/app/sites/new/SiteRegistrationOnlyWizard";

afterEach(() => vi.unstubAllGlobals());

describe("현장 등록 기본 ID", () => {
  it("uses one valid, human-editable identifier shape", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "f3d870db-1c61-4d5c-830b-8924e9b4bc8f" });
    expect(createGeneratedSiteId(1_789_708_800_000)).toBe("site-mu6ies5c-f3d870db");
  });

  it("uses cryptographic random bytes when randomUUID is unavailable", () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => {
      bytes.fill(0);
      return bytes;
    });
    vi.stubGlobal("crypto", { getRandomValues });

    expect(createRegistrationUuid()).toBe("00000000-0000-4000-8000-000000000000");
    expect(createGeneratedSiteId(123)).toBe("site-3f-00000000");
    expect(getRandomValues).toHaveBeenCalledTimes(2);
    expect(getRandomValues.mock.calls[0][0]).toHaveLength(16);
  });
});
