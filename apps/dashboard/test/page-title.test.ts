import { NAV_ITEMS } from "@/components/nav/nav-items";
import { describe, expect, it } from "vitest";

import { resolvePageTitle } from "@/components/nav/page-title";

// topbar 는 "지금 어디인가"를 말한다. 경로 패턴이 하나 빠지면 그 화면만 조용히
// 제목을 잃는데, 타입체크·빌드로는 안 보인다(2026-08-04 렌더 확인에서 실제로
// 제목이 이전 화면에 머무는 결함을 잡았다 — 원인은 달랐지만 표면은 같다).

describe("정적 경로", () => {
  it.each([
    ["/", "홈"],
    ["/sites", "현장"],
    ["/sites/new", "현장 등록"],
    ["/events", "확인 항목"],
    ["/missions", "비행 임무 이력"],
    ["/field", "작업"],
    ["/field/new", "새 관측"],
    ["/field/inbox", "받은 업무"],
    ["/field/team", "팀 관리"],
    ["/more", "더보기"],
  ])("%s → %s", (pathname, expected) => {
    expect(resolvePageTitle(pathname)).toBe(expected);
  });
});

describe("동적 경로", () => {
  it("상세 화면은 대상 이름이 아니라 종류를 적는다 — 이름은 본문 h1 이 갖는다", () => {
    expect(resolvePageTitle("/sites/SITE-1")).toBe("현장 상세");
    expect(resolvePageTitle("/events/dev-1::evt-1")).toBe("확인 항목 상세");
    expect(resolvePageTitle("/missions/mission-1")).toBe("비행 임무 상세");
    expect(resolvePageTitle("/field/work-orders/WO-1")).toBe("현장 작업");
    expect(resolvePageTitle("/sites/SITE-1/observations/new")).toBe("새 관측");
    expect(resolvePageTitle("/sites/SITE-1/observations")).toBe("외부 관측 이력");
    expect(resolvePageTitle("/sites/SITE-1/observations/external-relative-volume-report-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")).toBe("외부 관측 결과");
    expect(resolvePageTitle("/field/M-1")).toBe("임무 복구");
  });

  it("현장 AI는 현장 작업공간 하위 화면이다", () => {
    expect(resolvePageTitle("/sites/SITE-1/ai")).toBe("KSI AI");
  });

  it("조사 계획은 현장 상세보다 먼저 매칭된다 — 순서가 뒤집히면 하위 화면이 상위 제목을 쓴다", () => {
    expect(resolvePageTitle("/sites/SITE-1/surveys/new")).toBe("조사 계획");
  });

  it("설계 기준면도 현장 상세보다 먼저 매칭된다", () => {
    expect(resolvePageTitle("/sites/SITE-1/design")).toBe("설계 기준면");
    expect(resolvePageTitle("/sites/SITE-1/design/")).toBe("설계 기준면");
  });

  it("작업구역(M4-C)도 마찬가지다 — 패턴이 없으면 topbar 가 제목을 잃는다", () => {
    expect(resolvePageTitle("/sites/SITE-1/work-areas")).toBe("작업구역");
    expect(resolvePageTitle("/sites/SITE-1/work-areas/")).toBe("작업구역");
  });

  it("후행 슬래시가 있어도 같은 제목이다", () => {
    expect(resolvePageTitle("/sites/SITE-1/")).toBe("현장 상세");
    expect(resolvePageTitle("/sites/SITE-1/surveys/new/")).toBe("조사 계획");
  });

  it("준비 중 섹션은 사이드바 라벨을 그대로 쓴다", () => {
    expect(resolvePageTitle("/coming-soon/fleet")).toBe("Dock·Edge 지원 범위");
    expect(resolvePageTitle("/coming-soon/알수없는섹션")).toBe("준비 중");
  });
});

describe("모르는 경로", () => {
  it("추측하지 않고 빈 제목을 준다", () => {
    expect(resolvePageTitle("/nope")).toBe("");
    expect(resolvePageTitle(null)).toBe("");
  });
});

describe("운영 지원 섹션", () => {
  it("운영 지원 라벨과 topbar 제목이 같은 말을 쓴다", () => {
    for (const key of ["missions", "settings"] as const) {
      const item = NAV_ITEMS.find((i) => i.key === key);
      expect(item, `${key} 항목이 없다`).toBeDefined();
      expect(item!.implemented).toBe(true);
      expect(resolvePageTitle(item!.href)).toBe(item!.label);
    }
  });

  it("구현된 항목은 /coming-soon 으로 가지 않는다", () => {
    for (const item of NAV_ITEMS) {
      if (item.implemented) expect(item.href.startsWith("/coming-soon/")).toBe(false);
    }
  });

  it("준비 중 항목은 여전히 /coming-soon 이고 그 화면이 라벨을 안다", () => {
    const pending = NAV_ITEMS.filter((i) => !i.implemented);
    expect(pending.map((i) => i.key)).toEqual(["fleet"]);
    for (const item of pending) {
      expect(item.href.startsWith("/coming-soon/")).toBe(true);
      expect(resolvePageTitle(item.href)).toBe(item.label);
    }
  });
});
