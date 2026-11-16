import { describe, expect, it } from "vitest";

import {
  PROJECT_SECTIONS,
  projectSectionHref,
  projectSwitchHref,
  siteDataHref,
  resolveProjectSection,
} from "@/components/nav/site-context";

const q = (value: string) => new URLSearchParams(value);

describe("프로젝트 섹션 해석 (ADR-KSI-043)", () => {
  it("섹션은 공간·자료·분석 순서다", () => {
    expect(PROJECT_SECTIONS.map((section) => section.key)).toEqual(["space", "data", "analysis"]);
  });

  it("프로젝트 루트는 공간이고 자료 패널(panel=materials|intake)과 자료 화면(/data)은 자료다", () => {
    expect(resolveProjectSection("/sites/s1", q(""))).toBe("space");
    expect(resolveProjectSection("/sites/s1", q("panel=materials"))).toBe("data");
    expect(resolveProjectSection("/sites/s1", q("panel=intake&workAreaId=w1"))).toBe("data");
    expect(resolveProjectSection("/sites/s1/data", q("workAreaId=w1&assetRef=a"))).toBe("data");
    expect(resolveProjectSection("/sites/s1", q("mode=compare"))).toBe("space");
  });

  it("분석 경로와 결과 모드는 분석이다", () => {
    expect(resolveProjectSection("/sites/s1/analysis", q(""))).toBe("analysis");
    expect(resolveProjectSection("/sites/s1/observations", q(""))).toBe("analysis");
    expect(resolveProjectSection("/sites/s1", q("mode=results"))).toBe("analysis");
  });

  it("영역·자료 준비 요청 같은 공간 하위 경로는 공간이다", () => {
    expect(resolveProjectSection("/sites/s1/work-areas", q(""))).toBe("space");
    expect(resolveProjectSection("/sites/s1/spatial-data-requests", q(""))).toBe("space");
    // 하위 경로의 panel 쿼리는 자료 패널이 아니다.
    expect(resolveProjectSection("/sites/s1/work-areas", q("panel=materials"))).toBe("space");
  });

  it("프로젝트 설정과 프로젝트 밖은 섹션이 없다", () => {
    expect(resolveProjectSection("/sites/s1", q("section=manage"))).toBeNull();
    expect(resolveProjectSection("/sites", q(""))).toBeNull();
    expect(resolveProjectSection("/sites/new", q(""))).toBeNull();
    expect(resolveProjectSection("/field", q(""))).toBeNull();
  });

  it("섹션 주소는 기존 라우트를 그대로 쓴다", () => {
    expect(projectSectionHref("s1", "space")).toBe("/sites/s1");
    expect(projectSectionHref("s1", "data")).toBe("/sites/s1/data");
    expect(projectSectionHref("s1", "analysis")).toBe("/sites/s1/analysis");
    expect(projectSectionHref("s1", null)).toBe("/sites/s1");
    expect(projectSwitchHref("s2", "data")).toBe("/sites/s2/data");
  });

  it("자료 섹션 주소는 값이 있는 조건만 싣는다", () => {
    expect(siteDataHref("s1")).toBe("/sites/s1/data");
    expect(siteDataHref("s1", { workAreaId: "w1", assetRef: "ksa", q: "north map", kind: "dsm", state: "inspected", cursor: "a/b", progress: true }))
      .toBe("/sites/s1/data?workAreaId=w1&assetRef=ksa&q=north+map&kind=dsm&state=inspected&cursor=a%2Fb&progress=1");
    expect(siteDataHref("s 1", { workAreaId: null, q: "", progress: false })).toBe("/sites/s%201/data");
  });
});
