import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ redirect: (href: string) => { throw new Error(href); } }));

import SiteProgressPage from "@/app/sites/[siteId]/progress/page";

describe("옛 등록 진행 주소", () => {
  it("자료 섹션의 등록 진행 서랍으로 보낸다", async () => {
    await expect(SiteProgressPage({ params: Promise.resolve({ siteId: "site-1" }) }))
      .rejects.toThrow("/sites/site-1/data?progress=1");
  });

  it("식별자는 주소용으로 인코딩한다", async () => {
    await expect(SiteProgressPage({ params: Promise.resolve({ siteId: "a b" }) }))
      .rejects.toThrow("/sites/a%20b/data?progress=1");
  });
});
