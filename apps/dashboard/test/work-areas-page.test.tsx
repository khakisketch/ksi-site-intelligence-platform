import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: (url: string) => { throw new Error(`NEXT_REDIRECT;replace;${url};307;`); },
}));

import SiteWorkAreasPage from "@/app/sites/[siteId]/work-areas/page";

const open = (searchParams?: Record<string, string | string[]>) => SiteWorkAreasPage({
  params: Promise.resolve({ siteId: "site-1" }),
  searchParams: searchParams ? Promise.resolve(searchParams) : undefined,
});

describe("옛 작업구역 주소", () => {
  it("공간의 영역 관리 보기로 보낸다", async () => {
    await expect(open()).rejects.toThrow("/sites/site-1?panel=areas&manage=1");
  });

  it("고른 구역 힌트를 싣고, 형식이 맞지 않는 값은 버린다", async () => {
    await expect(open({ workAreaId: "area-1" })).rejects.toThrow("/sites/site-1?panel=areas&workAreaId=area-1&manage=1");
    await expect(open({ workAreaId: ["a", "b"] })).rejects.toThrow("/sites/site-1?panel=areas&manage=1");
  });
});
