import { describe, expect, it } from "vitest";

import { formatRelativeKo } from "@/lib/datetime";

// 서울 2026-11-16 15:00 = 06:00Z
const now = new Date("2026-11-16T06:00:00Z");

describe("formatRelativeKo", () => {
  it("방금·분·시간은 같은 서울 날짜 안에서 센다", () => {
    expect(formatRelativeKo("2026-11-16T05:59:40Z", now)).toBe("방금");
    expect(formatRelativeKo("2026-11-16T05:30:00Z", now)).toBe("30분 전");
    expect(formatRelativeKo("2026-11-16T01:00:00Z", now)).toBe("5시간 전");
  });

  it("날짜 경계는 서버 시간대가 아니라 서울 달력이다", () => {
    // 서울 11-15 23:30(= 14:30Z)은 지금(서울 11-16 15:00)부터 15시간 30분 전이지만 달력으로는 어제다.
    expect(formatRelativeKo("2026-11-15T14:30:00Z", now)).toBe("어제");
    // 서울 11-16 00:10(= 11-15T15:10Z)은 같은 날이라 시간으로 센다.
    expect(formatRelativeKo("2026-11-15T15:10:00Z", now)).toBe("14시간 전");
  });

  it("일주일 안은 N일 전, 그 뒤는 날짜(같은 해는 연도 생략)다", () => {
    expect(formatRelativeKo("2026-11-14T06:00:00Z", now)).toBe("2일 전");
    expect(formatRelativeKo("2026-11-10T06:00:00Z", now)).toBe("6일 전");
    expect(formatRelativeKo("2026-11-09T06:00:00Z", now)).toBe("11. 9.");
    expect(formatRelativeKo("2025-12-30T06:00:00Z", now)).toBe("2025. 12. 30.");
  });

  it("미래 시각과 잘못된 값은 꾸미지 않는다", () => {
    expect(formatRelativeKo("2026-11-16T09:00:00Z", now)).toBe("방금");
    expect(formatRelativeKo("not-a-date", now)).toBe("not-a-date");
  });
});
