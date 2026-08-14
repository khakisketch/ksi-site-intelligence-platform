import { describe, expect, it } from "vitest";

import { formatKoreanDate, formatKoreanDateTime, SEOUL_TIME_ZONE } from "@/lib/datetime";

// 회귀 방지: 서버가 어느 시간대로 돌든(테스트 러너의 TZ 도 포함) 한국 시각으로
// 찍혀야 한다 — 예전 formatMoment 관용구(timeZone 없이 toLocaleString)는 이
// 프로세스의 로컬 시간대로 찍혔다. UTC 자정은 한국 시각으로 09:00 이다 — 이
// 어긋남이 자정 근처에서는 날짜 자체를 바꾼다는 것이 버그의 핵심이었다.
describe("formatKoreanDateTime", () => {
  it("UTC 자정을 한국 시각 09:00 로 찍는다 — 프로세스 시간대와 무관하게", () => {
    const formatted = formatKoreanDateTime("2026-08-12T00:00:00.000Z", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    expect(formatted).toContain("09:00");
  });

  it("오전/오후 locale 표현에 기대지 않고 24시간제로 같은 문자열을 만든다", () => {
    expect(formatKoreanDateTime("2026-08-13T13:07:59.000Z")).toBe("2026. 8. 13. 22:07:59");
    expect(
      formatKoreanDateTime("2026-08-13T13:07:59.000Z", {
        dateStyle: "medium",
        timeStyle: "short",
      }),
    ).toBe("2026. 8. 13. 22:07");
  });

  it("날짜만 쓰는 화면도 서울 기준 날짜를 쓴다", () => {
    expect(formatKoreanDate("2026-08-12T15:30:00.000Z")).toBe("2026. 8. 13.");
  });

  it("한국 자정 근처 UTC 시각은 한국 날짜로 다음 날이다", () => {
    // 한국 시각 2026-08-13 00:30 == UTC 2026-08-12 15:30
    const formatted = formatKoreanDateTime("2026-08-12T15:30:00.000Z", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    expect(formatted).toContain("2026");
    expect(formatted).toContain("13");
  });

  it("파싱할 수 없는 문자열은 원문을 그대로 돌려준다", () => {
    expect(formatKoreanDateTime("이건-날짜가-아님")).toBe("이건-날짜가-아님");
  });

  it("SEOUL_TIME_ZONE 은 Asia/Seoul 이다", () => {
    expect(SEOUL_TIME_ZONE).toBe("Asia/Seoul");
  });
});
