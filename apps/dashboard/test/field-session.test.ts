import { describe, expect, it } from "vitest";

import { classifyFieldSessionFailure } from "@/app/field/field-session";

// /field 는 세션 실패에 리다이렉트하지 않는다(proxy.ts PUBLIC_PATHS). 그 대신 이
// 판정이 화면을 정한다. 여기서 가르는 축은 하나다 — **다시 로그인하면 풀리는가.**
// 그 축이 틀리면 두 방향 모두 현장에서 비싸다:
//   ① 풀리는데 오류로 처리 → 운영자가 할 수 있는 일이 있는데 화면이 막다른 길이 된다
//   ② 안 풀리는데 폼을 보여줌 → 토큰을 몇 번이고 다시 입력하며 자기 잘못을 찾는다

describe("인라인 로그인으로 푸는 실패", () => {
  it("세션 쿠키가 아예 없으면 폼만 보여준다 — 없던 세션이 만료됐다고 말하지 않는다", () => {
    const verdict = classifyFieldSessionFailure({ kind: "no-session" });
    expect(verdict).toEqual({ kind: "login", notice: null });
  });

  it("401 은 만료 사유를 붙여 폼을 보여준다", () => {
    const verdict = classifyFieldSessionFailure({ kind: "api", status: 401 });
    expect(verdict.kind).toBe("login");
    if (verdict.kind !== "login") return;
    expect(verdict.notice).toContain("세션이 만료");
  });

  it("403 도 폼을 보여준다 — 조종기는 공용 장비라 해법이 '다른 계정으로 로그인'이다", () => {
    const verdict = classifyFieldSessionFailure({ kind: "api", status: 403 });
    expect(verdict.kind).toBe("login");
    if (verdict.kind !== "login") return;
    expect(verdict.notice).toContain("다른 계정");
  });
});

describe("로그인으로 풀리지 않는 실패", () => {
  it("Core 에 닿지 못한 경우 폼을 보여주지 않는다", () => {
    const verdict = classifyFieldSessionFailure({ kind: "unreachable" });
    expect(verdict.kind).toBe("error");
  });

  it.each([500, 502, 503])("%d 는 서버 문제다 — 폼이 아니라 사유를 보여준다", (status) => {
    const verdict = classifyFieldSessionFailure({ kind: "api", status });
    expect(verdict.kind).toBe("error");
  });
});

describe("판정 전체", () => {
  it("어떤 사유든 사람이 읽을 문장을 남긴다 — 빈 화면으로 끝나는 경로가 없다", () => {
    const failures = [
      { kind: "no-session" } as const,
      { kind: "unreachable" } as const,
      ...[400, 401, 403, 404, 500, 503].map((status) => ({ kind: "api" as const, status })),
    ];
    for (const failure of failures) {
      const verdict = classifyFieldSessionFailure(failure);
      if (verdict.kind === "error") {
        expect(verdict.message.length).toBeGreaterThan(0);
      } else {
        // login 은 notice 가 null 일 수 있다(첫 방문) — 그때는 폼 자체가 설명이다.
        expect(verdict.notice === null || verdict.notice.length > 0).toBe(true);
      }
    }
  });
});
