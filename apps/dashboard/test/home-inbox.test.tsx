// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { HomeInbox, type HomeInboxItem } from "@/app/HomeInbox";
import { HomeProjects, parseHomeProjectSort } from "@/app/HomeProjects";
import { HomeRecentUpdates } from "@/app/HomeRecentUpdates";
import type { SiteView } from "@/lib/core-api/types";

afterEach(cleanup);

function item(overrides: Partial<HomeInboxItem> = {}): HomeInboxItem {
  return {
    key: "a", kind: "review", title: "분석 결과를 검토하세요", siteName: "송도 A블록", subject: "2구역 성토부",
    href: "/sites/site-1/analysis", actionLabel: "결과 보기", observedAt: "2026-10-21T01:17:00Z", timeLabel: "분석 생성", ...overrides,
  };
}

function site(id: string, name: string, updatedAt: string, status: SiteView["status"] = "PATROL_READY"): SiteView {
  return { siteId: id, name, status, updatedAt, registeredAt: "2026-08-01T00:00:00Z", aoi: null } as unknown as SiteView;
}

describe("HomeInbox", () => {
  it("제목은 할 일, 프로젝트·대상은 보조, 행동은 하나다 — 큰 표지·사진 없이", () => {
    render(<HomeInbox items={[item()]} complete />);
    const row = within(screen.getByRole("region", { name: "확인할 것 목록" })).getByRole("article");
    expect(within(row).getByRole("heading", { level: 3, name: "분석 결과를 검토하세요" })).toBeTruthy();
    expect(row.textContent).toContain("송도 A블록");
    expect(row.textContent).toContain("2구역 성토부");
    expect(within(row).getAllByRole("link")).toHaveLength(1);
    expect(within(row).getByRole("link", { name: "결과 보기" }).getAttribute("href")).toBe("/sites/site-1/analysis");
    expect(row.querySelector("img, figure, [class*='min-h-[']")).toBeNull();
  });

  it("시각은 상대 시각만 보이고, 그 시각의 뜻은 툴팁과 보조기술에 남긴다(촬영일로 오독하지 않게)", () => {
    render(<HomeInbox items={[item({ timeLabel: "분석 생성" })]} complete />);
    const time = document.querySelector("time")!;
    expect(time.getAttribute("datetime")).toBe("2026-10-21T01:17:00Z");
    expect(time.getAttribute("title")).toContain("분석 생성");
    expect(time.textContent).toContain("분석 생성");
    expect(document.body.textContent).not.toMatch(/촬영일|촬영 시각|관측일시/);
  });

  it("숫자는 보이는 줄 수와 같고, 첫 행만 주 행동이다", () => {
    render(<HomeInbox items={[item({ key: "a" }), item({ key: "b" }), item({ key: "c" })]} complete />);
    expect(document.querySelector("[data-home-inbox-count]")!.textContent).toBe("3");
    const links = screen.getAllByRole("link", { name: "결과 보기" });
    expect(links[0]!.className).toContain("btn-primary");
    expect(links[1]!.className).not.toContain("btn-primary");
  });

  it("5건을 넘으면 나머지는 접어 두되 숫자는 전체를 센다", () => {
    const many = Array.from({ length: 7 }, (_, index) => item({ key: `k${index}` }));
    render(<HomeInbox items={many} complete />);
    expect(document.querySelector("[data-home-inbox-count]")!.textContent).toBe("7");
    const more = screen.getByText("외 2건 더 보기").closest("details")!;
    expect(more.hasAttribute("open")).toBe(false);
    expect(within(more).getAllByRole("article")).toHaveLength(2);
  });

  it("다 읽지 못했으면 하한(N+), 아무것도 모르면 —, 다 읽었고 없으면 0이다 — 모름을 0이라 말하지 않는다", () => {
    const { rerender } = render(<HomeInbox items={[item()]} complete={false} />);
    expect(document.querySelector("[data-home-inbox-count]")!.textContent).toBe("1+");
    rerender(<HomeInbox items={[]} complete={false} />);
    expect(document.querySelector("[data-home-inbox-count]")!.textContent).toBe("—");
    expect(screen.getByText("확인할 것을 찾지 못했습니다")).toBeTruthy();
    rerender(<HomeInbox items={[]} complete />);
    expect(document.querySelector("[data-home-inbox-count]")!.textContent).toBe("0");
    expect(screen.getByText("지금 확인할 것이 없습니다")).toBeTruthy();
  });

  it("기술 참조는 접어 두고, 안내는 목록 맨 아래에 둔다", () => {
    render(<HomeInbox items={[item({ technicalRef: "분석 a1 · 영역 w1" })]} complete={false} notice={<p>일부를 확인하지 못했습니다.</p>} />);
    const ref = screen.getByText("식별 상세").closest("details")!;
    expect(ref.hasAttribute("open")).toBe(false);
    const region = screen.getByRole("region", { name: "확인할 것 목록" });
    expect(region.lastElementChild!.textContent).toContain("일부를 확인하지 못했습니다.");
  });
});

describe("HomeProjects", () => {
  const sites = [
    site("s-old", "다 프로젝트", "2026-10-01T00:00:00Z"),
    site("s-new", "나 프로젝트", "2026-11-10T00:00:00Z", "BASELINE_MAPPING"),
    site("s-mid", "가 프로젝트", "2026-10-20T00:00:00Z"),
  ];
  const names = () => screen.getAllByRole("article").map((card) => card.querySelector("a span.truncate")!.textContent);

  it("기본은 최근 갱신순이고, 이름순·확인할 것 먼저로 바꿀 수 있다", () => {
    const attention = new Map([["s-old", 2], ["s-mid", 1]]);
    const { rerender } = render(<HomeProjects sites={sites} attentionBySite={attention} sort="recent" />);
    expect(names()).toEqual(["나 프로젝트", "가 프로젝트", "다 프로젝트"]);
    rerender(<HomeProjects sites={sites} attentionBySite={attention} sort="name" />);
    expect(names()).toEqual(["가 프로젝트", "나 프로젝트", "다 프로젝트"]);
    rerender(<HomeProjects sites={sites} attentionBySite={attention} sort="attention" />);
    expect(names()).toEqual(["다 프로젝트", "가 프로젝트", "나 프로젝트"]);
  });

  it("카드는 이름·상태·갱신·확인 필요 표시와 자료·분석 바로가기만 두고 큰 타일을 두지 않는다", () => {
    render(<HomeProjects sites={sites} attentionBySite={new Map([["s-old", 2]])} sort="recent" />);
    const card = screen.getAllByRole("article").find((node) => node.textContent!.includes("다 프로젝트"))!;
    expect(card.textContent).toContain("확인 필요");
    expect(within(card).getByRole("link", { name: "자료" }).getAttribute("href")).toBe("/sites/s-old/data");
    expect(within(card).getByRole("link", { name: "분석" }).getAttribute("href")).toBe("/sites/s-old/analysis");
    expect(card.querySelector("[class*='aspect-'], [class*='min-h-[']")).toBeNull();
    // 확인할 것이 없는 프로젝트에는 배지가 없다.
    const quiet = screen.getAllByRole("article").find((node) => node.textContent!.includes("나 프로젝트"))!;
    expect(quiet.textContent).not.toContain("확인 필요");
    expect(screen.getByRole("heading", { name: /^프로젝트 3/ })).toBeTruthy();
  });

  it("정렬 값은 모르는 값을 최근 갱신순으로 돌린다", () => {
    expect(parseHomeProjectSort("name")).toBe("name");
    expect(parseHomeProjectSort(["attention", "name"])).toBe("attention");
    expect(parseHomeProjectSort("bogus")).toBe("recent");
    expect(parseHomeProjectSort(undefined)).toBe("recent");
  });
});

describe("HomeRecentUpdates", () => {
  it("한 줄씩 종류·프로젝트·제목·상대 시각만 둔다", () => {
    render(<HomeRecentUpdates items={[{ key: "r1", siteName: "김포", label: "새 결과", title: "외부 작업", href: "/field/work-orders/w1", observedAt: "2026-10-21T01:17:00Z", timeLabel: "결과 보고" }]} />);
    const link = screen.getByRole("link", { name: "김포, 새 결과, 외부 작업" });
    expect(link.getAttribute("href")).toBe("/field/work-orders/w1");
    expect(link.querySelector("time")!.getAttribute("title")).toContain("결과 보고");
    expect(screen.queryByText(/결과와 사람이 정리한 안건만/)).toBeNull();
  });

  it("없으면 섹션을 만들지 않는다", () => {
    render(<HomeRecentUpdates items={[]} />);
    expect(screen.queryByRole("heading")).toBeNull();
  });
});
