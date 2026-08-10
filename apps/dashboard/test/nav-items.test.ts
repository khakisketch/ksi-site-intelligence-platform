import { describe, expect, it } from "vitest";

import {
  DESKTOP_NAV_GROUPS,
  DESKTOP_NAV_ITEMS,
  MOBILE_TAB_ITEMS,
  NAV_ITEMS,
} from "@/components/nav/nav-items";

// 이 파일이 고정하는 것은 **도달 가능성**이다. 사이드바 그룹이 키 화이트리스트로
// 항목을 고르던 시절, 어느 목록에도 안 걸린 항목은 오류 없이 그냥 사라졌다 —
// 2026-08-08 에 assets·world·reports·settings 가 "준비 중"에서 실동작으로
// 승격되면서 정확히 그렇게 사라졌고, /reports(두 시점 비교 결과 화면 전체)는
// 임무 상세 안의 버튼 말고는 데스크톱에서 갈 방법이 없었다. 화면은 정상으로
// 보이므로 렌더 테스트로도 안 잡힌다 — 목록 자체를 대조해야 잡힌다.

describe("DESKTOP_NAV_GROUPS", () => {
  it("[핵심][회귀] 데스크톱 항목이 하나도 빠짐없이 어느 그룹엔가 들어간다", () => {
    const grouped = DESKTOP_NAV_GROUPS.flatMap((group) => group.items.map((i) => i.key));
    const expected = DESKTOP_NAV_ITEMS.map((i) => i.key);
    expect([...grouped].sort()).toEqual([...expected].sort());
  });

  it("[핵심][회귀] 한 항목이 두 그룹에 중복해서 들어가지 않는다", () => {
    const grouped = DESKTOP_NAV_GROUPS.flatMap((group) => group.items.map((i) => i.key));
    expect(grouped).toHaveLength(new Set(grouped).size);
  });

  it("[핵심] PRD §7.1 이 못박은 데스크톱 10항목이 그대로 있다", () => {
    // 명칭·순서 둘 다 PRD 고정값이다(docs/product/MASTER_PRD_v3.0.md §7.1).
    const grouped = DESKTOP_NAV_GROUPS.flatMap((group) => group.items.map((i) => i.label));
    expect(grouped).toEqual([
      "홈",
      "현장",
      "임무",
      "이벤트",
      "자산·시설물",
      "2D·3D World",
      "보고서",
      "Fleet·Edge",
      "Data·AI",
      "설정",
    ]);
  });

  it("그룹 순서가 NAV_ITEMS 순서를 뒤집지 않는다(PRD 가 순서를 고정한다)", () => {
    const order = new Map(NAV_ITEMS.map((item, index) => [item.key, index]));
    const grouped = DESKTOP_NAV_GROUPS.flatMap((group) => group.items.map((i) => i.key));
    const positions = grouped.map((key) => order.get(key)!);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
  });

  it("빈 그룹은 그리지 않는다(라벨만 남은 칸이 생기지 않게)", () => {
    for (const group of DESKTOP_NAV_GROUPS) {
      expect(group.items.length).toBeGreaterThan(0);
    }
  });
});

describe("MOBILE_TAB_ITEMS", () => {
  it("PRD §7.1 모바일 하단 5탭 그대로다", () => {
    expect(MOBILE_TAB_ITEMS.map((i) => i.label)).toEqual([
      "오늘",
      "현장",
      "임무",
      "이벤트",
      "더보기",
    ]);
  });

  it("데스크톱에서만 보이는 항목은 '더보기'가 받아준다 — 모바일에서도 도달 가능해야 한다", () => {
    // /more 화면이 실제로 그 목록을 그린다(app/more/page.tsx). 여기서는 그 진입점이
    // 탭에 남아 있는지만 고정한다 — 진입점이 사라지면 모바일에서 절반이 사라진다.
    expect(MOBILE_TAB_ITEMS.some((i) => i.href === "/more")).toBe(true);
  });
});
