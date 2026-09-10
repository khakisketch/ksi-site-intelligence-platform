import { describe, expect, it, vi } from "vitest";

import { createGeneratedSiteId } from "@/app/sites/new/SiteRegistrationOnlyWizard";

describe("현장 등록 기본 ID", () => {
  it("uses one valid, human-editable identifier shape", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "f3d870db-1c61-4d5c-830b-8924e9b4bc8f" });
    expect(createGeneratedSiteId(1_789_708_800_000)).toBe("site-mu6ies5c-f3d870db");
    vi.unstubAllGlobals();
  });
});
