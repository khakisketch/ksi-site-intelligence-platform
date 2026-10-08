/** 콘솔 셸(Console v2 §0)의 **판정 로직** 회귀.
 *
 * 이 저장소의 프런트 테스트 규약대로 렌더는 보지 않는다(vitest.config.ts) — 여기서
 * 고정하는 것은 "무엇이 검색되는가 · 어떤 키가 무엇을 하는가 · 수신 표시가 언제
 * 거짓이 되는가" 세 가지다. 셋 다 렌더 캡처로는 잡히지 않는 회귀다.
 */

import { describe, expect, it } from "vitest";

import { isBackVisible, resolveParentNavigation } from "../src/components/nav/BackButton";
import {
  OFFLINE_AFTER_S,
  STALE_AFTER_S,
  resolveLiveStatus,
} from "../src/components/console/live-status";
import {
  filterPaletteItems,
  matchScore,
  moveActiveIndex,
  normalizeQuery,
  type PaletteItem,
} from "../src/components/console/palette-items";
import { isTypingTarget, resolveShortcut } from "../src/components/console/shortcuts";
import { commandModifierLabel } from "../src/components/console/command-modifier";

const ITEMS: PaletteItem[] = [
  { key: "screen:sites", label: "현장", group: "화면", href: "/sites" },
  { key: "screen:work", label: "작업", group: "화면", href: "/field" },
  { key: "screen:fleet", label: "Fleet·Edge", group: "화면", href: "/coming-soon/fleet", pending: true },
  {
    key: "site:S-1",
    label: "광교 A3블록 공동주택 신축",
    group: "현장",
    href: "/sites/S-1",
    hint: "S-2411-GJ · 순찰 중",
  },
];

describe("커맨드 팔레트 검색", () => {
  it("빈 검색어는 원래 순서를 그대로 돌려준다", () => {
    const result = filterPaletteItems(ITEMS, "   ");
    expect(result.map((i) => i.key)).toEqual(ITEMS.map((i) => i.key));
  });

  it("라벨 시작 일치가 부분 일치보다 먼저 온다", () => {
    const items: PaletteItem[] = [
      { key: "a", label: "재관측 임무", group: "화면", href: "/a" },
      { key: "b", label: "임무", group: "화면", href: "/b" },
    ];
    // "임무"는 b 의 시작이고 a 의 중간이다 — b 가 먼저다.
    expect(filterPaletteItems(items, "임무").map((i) => i.key)).toEqual(["b", "a"]);
  });

  it("현장은 이름뿐 아니라 ID·상태로도 찾힌다", () => {
    // 현장명을 기억 못 해도 ID 로 도달할 수 있어야 한다.
    expect(filterPaletteItems(ITEMS, "S-2411").map((i) => i.key)).toEqual(["site:S-1"]);
    expect(filterPaletteItems(ITEMS, "순찰").map((i) => i.key)).toEqual(["site:S-1"]);
  });

  it("대소문자와 좌우 공백을 무시한다", () => {
    expect(normalizeQuery("  Fleet  ")).toBe("fleet");
    expect(filterPaletteItems(ITEMS, "  FLEET ").map((i) => i.key)).toEqual(["screen:fleet"]);
  });

  it("일치가 없으면 빈 목록이다 — 엉뚱한 항목을 채우지 않는다", () => {
    expect(filterPaletteItems(ITEMS, "존재하지않는것")).toEqual([]);
  });

  it("준비 중 항목도 검색된다 — 링크를 숨기지 않는다(UX 목표 §6)", () => {
    const hit = filterPaletteItems(ITEMS, "fleet")[0];
    expect(hit?.pending).toBe(true);
  });

  it("점수는 시작 0 · 부분 1 · 힌트 2 세 단계뿐이다", () => {
    const site = ITEMS[3]!;
    expect(matchScore(site, "광교")).toBe(0);
    expect(matchScore(site, "공동주택")).toBe(1);
    expect(matchScore(site, "순찰")).toBe(2);
    expect(matchScore(site, "없는말")).toBeNull();
  });
});

describe("팔레트 커서 이동", () => {
  it("목록 끝에서 멈춘다 — 순환하지 않는다", () => {
    expect(moveActiveIndex(0, -1, 4)).toBe(0);
    expect(moveActiveIndex(3, 1, 4)).toBe(3);
    expect(moveActiveIndex(1, 1, 4)).toBe(2);
  });

  it("빈 목록에서도 안전하다", () => {
    expect(moveActiveIndex(0, 1, 0)).toBe(0);
  });
});

describe("전역 단축키", () => {
  const input = { tagName: "INPUT" };

  it("⌘K / Ctrl+K 는 입력 중에도 팔레트를 연다", () => {
    expect(resolveShortcut({ key: "k", metaKey: true })).toBe("palette");
    expect(resolveShortcut({ key: "K", ctrlKey: true, target: input })).toBe("palette");
  });

  it("? 는 도움말이지만 **입력 중에는 양보한다**", () => {
    expect(resolveShortcut({ key: "?" })).toBe("help");
    // 사용자가 검색창에 물음표를 칠 때 도움말이 열리면 그건 버그다.
    expect(resolveShortcut({ key: "?", target: input })).toBeNull();
    expect(resolveShortcut({ key: "?", target: { tagName: "TEXTAREA" } })).toBeNull();
    expect(resolveShortcut({ key: "?", target: { isContentEditable: true } })).toBeNull();
  });

  it("Esc 는 입력 중에도 살아 있다 — 팔레트가 입력을 품고 있기 때문이다", () => {
    expect(resolveShortcut({ key: "Escape", target: input })).toBe("close");
  });

  it("수식키가 붙은 평범한 키는 가로채지 않는다", () => {
    expect(resolveShortcut({ key: "?", altKey: true })).toBeNull();
    expect(resolveShortcut({ key: "a" })).toBeNull();
  });

  it("입력 자리 판별은 대소문자를 가리지 않는다", () => {
    expect(isTypingTarget({ tagName: "input" })).toBe(true);
    expect(isTypingTarget({ tagName: "DIV" })).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe("단축키 안내", () => {
  it("Apple 계열은 Command, 나머지는 Ctrl로 표시한다", () => {
    expect(commandModifierLabel("MacIntel")).toBe("⌘");
    expect(commandModifierLabel("iPhone")).toBe("⌘");
    expect(commandModifierLabel("Linux x86_64")).toBe("Ctrl");
    expect(commandModifierLabel("Win32")).toBe("Ctrl");
  });
});

describe("라이브 수신 표시", () => {
  it("최근 수신이면 초록 + 맥동", () => {
    const status = resolveLiveStatus(12);
    expect(status.tone).toBe("live");
    expect(status.label).toBe("마지막 수신 12초 전");
    expect(status.pulse).toBe(true);
  });

  it("문턱을 넘으면 지연 — 맥동을 멈춘다", () => {
    const status = resolveLiveStatus(STALE_AFTER_S);
    expect(status.tone).toBe("stale");
    expect(status.pulse).toBe(false);
  });

  it("오래 끊기면 끊김으로 강등하고 **언제부터인지 함께 밝힌다**", () => {
    const status = resolveLiveStatus(OFFLINE_AFTER_S);
    expect(status.tone).toBe("offline");
    expect(status.dotClass).toBe("bg-crit");
    expect(status.label).toContain("수신 끊김");
    expect(status.label).toContain("분 전");
  });

  it("사용자가 끈 것과 끊긴 것을 구분한다", () => {
    const paused = resolveLiveStatus(999, true);
    expect(paused.tone).toBe("stale");
    expect(paused.label).toBe("실시간 갱신 꺼짐");
    expect(paused.pulse).toBe(false);
  });

  it("시계 역행(음수 경과)에도 깨지지 않는다", () => {
    expect(resolveLiveStatus(-5).label).toBe("마지막 수신 0초 전");
  });

  it("경과가 길어지면 분·시간으로 접는다", () => {
    expect(resolveLiveStatus(90, true).label).toBe("실시간 갱신 꺼짐");
    expect(resolveLiveStatus(90).label).toBe("마지막 수신 1분 전");
    expect(resolveLiveStatus(7200).label).toContain("2시간 전");
  });
});

describe("뒤로가기 노출 규칙", () => {
  it("최상위 화면에는 없다 — 갈 곳이 없는 버튼을 두지 않는다", () => {
    expect(isBackVisible("/")).toBe(false);
    expect(isBackVisible("/sites")).toBe(false);
    expect(isBackVisible("/field")).toBe(false);
    expect(isBackVisible("/events")).toBe(false);
  });

  it("하위 화면은 브라우저 이력이 아닌 결정적인 부모 화면으로 이동한다", () => {
    expect(isBackVisible("/sites/S-1")).toBe(true);
    expect(isBackVisible("/field/work-orders/WO-1")).toBe(true);
    expect(isBackVisible("/coming-soon/fleet")).toBe(true);
    expect(resolveParentNavigation("/sites/S-1")).toEqual({ href: "/sites/S-1", label: "현장" });
    expect(resolveParentNavigation("/field/work-orders/WO-1")).toEqual({ href: "/field", label: "작업" });
    expect(resolveParentNavigation("/sites/S-1/design")).toEqual({ href: "/sites/S-1", label: "현장" });
  });

  it("로그인과 retired /field/M-1 경로에는 뒤로가기가 없고 work-order 상세에는 있다", () => {
    expect(isBackVisible("/login")).toBe(false);
    expect(isBackVisible("/field/M-1")).toBe(false);
    expect(isBackVisible("/field/work-orders/WO-1")).toBe(true);
  });

  it("경로를 모르면 그리지 않는다", () => {
    expect(isBackVisible(null)).toBe(false);
    expect(resolveParentNavigation("/sites/new")).toBeNull();
    expect(resolveParentNavigation("/sites/S-1/observations/new")).toEqual({ href: "/sites/S-1", label: "현장" });
  });
});
