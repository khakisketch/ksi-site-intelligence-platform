import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { API_ERROR_MESSAGE } from "@/lib/core-api/labels";

/**
 * 낙관적 동시성 토큰의 **UI 배선**을 고정한다.
 *
 * 서버는 `expectedBundleDigest` 를 받아 409 STALE_EVENT_VIEW 로 막지만, 유일한
 * 운영자 화면이 그 값을 안 보내면 기능이 없는 것과 같다 — 실제로 독립 재검토가
 * "서버는 완결, UI 는 미배선"으로 잡았다. 컴포넌트는 "use client" 라 노드
 * 환경에서 렌더할 수 없으므로 소스에서 배선 지점을 확인한다.
 */
const ACTIONS_SOURCE = readFileSync(
  join(process.cwd(), "src/app/events/[eventKey]/EventActions.tsx"),
  "utf8",
);

describe("전이 요청의 낙관적 동시성 토큰", () => {
  it("submit 이 모든 전이 본문에 expectedBundleDigest 를 싣는다", () => {
    expect(ACTIONS_SOURCE).toMatch(/expectedBundleDigest:\s*bundleDigest/);
  });

  it("토큰을 props 로 받는다 — 컴포넌트가 스스로 계산하지 않는다", () => {
    // 클라이언트가 정규화 규약을 재구현하면 JSON 표기 차이 하나로 영구 409 가 된다.
    expect(ACTIONS_SOURCE).toMatch(/bundleDigest:\s*string/);
    expect(ACTIONS_SOURCE).not.toMatch(/sha256|createHash|digest\(/);
  });

  it("두 사용처(상세 페이지·마스터 디테일 패널)가 모두 토큰을 넘긴다", () => {
    for (const relative of [
      "src/app/events/[eventKey]/page.tsx",
      "src/app/events/EventDetailPanel.tsx",
    ]) {
      const source = readFileSync(join(process.cwd(), relative), "utf8");
      expect(source, relative).toMatch(/bundleDigest=\{event\.bundleDigest\}/);
    }
  });
});

describe("STALE_EVENT_VIEW 라벨", () => {
  it("서버 코드가 사람 문구로 번역된다 — raw 코드 노출 금지", () => {
    const label = API_ERROR_MESSAGE.STALE_EVENT_VIEW;
    expect(label).toBeTruthy();
    expect(label).not.toContain("STALE_EVENT_VIEW");
    expect(label).toContain("새로고침");
  });
});
