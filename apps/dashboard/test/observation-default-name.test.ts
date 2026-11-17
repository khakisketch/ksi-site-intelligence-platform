import { describe, expect, it } from "vitest";

import { defaultObservationName, koreanCalendarDate } from "@/lib/observation-default-name";

describe("defaultObservationName", () => {
  it("구역 하나는 이름과 한국 날짜로 만든다", () => {
    expect(defaultObservationName(["동측 절토면"], new Date("2026-11-17T03:00:00Z"))).toBe("동측 절토면 · 2026-11-17 자료");
  });

  it("날짜는 한국 시각 기준이다(UTC 15시 이후는 다음 날)", () => {
    expect(koreanCalendarDate(new Date("2026-11-17T14:59:59Z"))).toBe("2026-11-17");
    expect(koreanCalendarDate(new Date("2026-11-17T15:00:00Z"))).toBe("2026-11-18");
  });

  it("구역이 여럿이면 첫 구역 외 N곳으로 줄인다", () => {
    expect(defaultObservationName(["동측", "서측", "북측"], new Date("2026-11-17T03:00:00Z"))).toBe("동측 외 2곳 · 2026-11-17 자료");
  });

  it("구역이 없으면 날짜만 쓰고, 공백뿐인 이름은 버린다", () => {
    expect(defaultObservationName([], new Date("2026-11-17T03:00:00Z"))).toBe("2026-11-17 자료");
    expect(defaultObservationName(["  ", "동측"], new Date("2026-11-17T03:00:00Z"))).toBe("동측 · 2026-11-17 자료");
  });

  it("긴 구역 이름은 200자 안으로 줄인다", () => {
    const name = defaultObservationName(["가".repeat(400)], new Date("2026-11-17T03:00:00Z"));
    expect(name.length).toBeLessThanOrEqual(200);
    expect(name.endsWith(" · 2026-11-17 자료")).toBe(true);
    expect(name).toContain("…");
  });
});
