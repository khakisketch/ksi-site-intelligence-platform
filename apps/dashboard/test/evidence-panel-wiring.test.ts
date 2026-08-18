import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 같은 사건의 같은 증거를 두 화면이 다르게 그리면 그중 하나는 반드시 거짓말이 된다.
// 분할뷰는 오랫동안 자리표시만 그리며 "열람 경로 준비 중"이라 말했는데, 그 경로는
// 이미 있었고 전체 화면은 그것을 쓰고 있었다(2026-08-17 수정). 소스를 직접 읽어
// 배선을 고정한다 — test/event-actions-token.test.ts 와 같은 방식이다.
const PANEL = readFileSync(
  join(process.cwd(), "src/app/events/EventDetailPanel.tsx"),
  "utf8",
);

describe("이벤트 분할뷰의 증거 배선", () => {
  it("[핵심] 전체 화면과 같은 EvidencePanel 을 쓴다", () => {
    expect(PANEL).toContain('from "./[eventKey]/EvidencePanel"');
    expect(PANEL).toContain("<EvidencePanel");
  });

  it("증거 유무를 번들 키 개수로 대신 재지 않는다", () => {
    // hasBundle 은 원시 번들 dict 의 키 유무여서 evidence.length 와 무관했다 —
    // 증거가 0건이어도 "수신돼 있습니다"라 말하고, 5건 있어도 "준비 중"이라 말했다.
    expect(PANEL).not.toContain("hasBundle");
  });

  it("이미 있는 열람 경로를 '준비 중'이라 말하지 않는다", () => {
    expect(PANEL).not.toContain("열람 경로 준비 중");
  });
});
