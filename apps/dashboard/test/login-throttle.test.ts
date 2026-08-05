import { beforeEach, describe, expect, it } from "vitest";

import {
  LOGIN_THROTTLE_LIMITS,
  checkLoginThrottle,
  recordLoginFailure,
  recordLoginSuccess,
  resetLoginThrottle,
} from "@/lib/core-api/login-throttle";

// 이 제품의 인증은 bearer 토큰 **하나**다 — 사용자명+비밀번호 조합이 아니라 단일
// 비밀이라, 무제한 추측이 가능하면 전체 보안이 토큰 엔트로피에만 걸린다.
// dev 토큰이 추측 가능한 리터럴(`dev-admin-token`)이라는 점이 그 위험을 실물로 보인다.

const { MAX_FAILURES, WINDOW_MS } = LOGIN_THROTTLE_LIMITS;
const T0 = 1_800_000_000_000;

beforeEach(() => {
  resetLoginThrottle();
});

describe("시도 제한", () => {
  it("한도까지는 통과시킨다 — 오타 몇 번이 잠금이 되면 안 된다", () => {
    for (let i = 0; i < MAX_FAILURES - 1; i++) {
      recordLoginFailure("1.2.3.4", T0);
      expect(checkLoginThrottle("1.2.3.4", T0).blocked).toBe(false);
    }
  });

  it("한도를 넘기면 차단하고 남은 시간을 알려준다", () => {
    for (let i = 0; i < MAX_FAILURES; i++) recordLoginFailure("1.2.3.4", T0);
    const state = checkLoginThrottle("1.2.3.4", T0);
    expect(state.blocked).toBe(true);
    expect(state.retryAfterSeconds).toBeGreaterThan(0);
    expect(state.retryAfterSeconds).toBeLessThanOrEqual(WINDOW_MS / 1000);
  });

  it("창이 지나면 다시 허용한다", () => {
    for (let i = 0; i < MAX_FAILURES; i++) recordLoginFailure("1.2.3.4", T0);
    expect(checkLoginThrottle("1.2.3.4", T0 + WINDOW_MS - 1).blocked).toBe(true);
    expect(checkLoginThrottle("1.2.3.4", T0 + WINDOW_MS).blocked).toBe(false);
  });

  it("성공하면 카운터가 사라진다 — 잠금이 정상 사용을 방해하면 우회로를 찾게 된다", () => {
    for (let i = 0; i < MAX_FAILURES - 1; i++) recordLoginFailure("1.2.3.4", T0);
    recordLoginSuccess("1.2.3.4");
    for (let i = 0; i < MAX_FAILURES - 1; i++) {
      recordLoginFailure("1.2.3.4", T0);
      expect(checkLoginThrottle("1.2.3.4", T0).blocked).toBe(false);
    }
  });

  it("키가 다르면 서로 영향을 주지 않는다", () => {
    for (let i = 0; i < MAX_FAILURES; i++) recordLoginFailure("1.2.3.4", T0);
    expect(checkLoginThrottle("1.2.3.4", T0).blocked).toBe(true);
    expect(checkLoginThrottle("5.6.7.8", T0).blocked).toBe(false);
  });

  it("식별 불가 클라이언트도 제한 대상이다", () => {
    // 헤더를 지우면 제한이 풀리는 구조면 공격자는 헤더만 지우면 된다.
    for (let i = 0; i < MAX_FAILURES; i++) recordLoginFailure("unidentified", T0);
    expect(checkLoginThrottle("unidentified", T0).blocked).toBe(true);
  });

  it("창은 첫 실패에서 시작한다 — 실패가 이어져도 창이 밀리지 않는다", () => {
    // 매 실패마다 창을 갱신하면(sliding) 공격자가 계속 시도하는 한 영원히 잠기고,
    // 반대로 창이 리셋되면 제한이 무의미해진다. 첫 실패 기준 고정 창이 그 중간이다.
    recordLoginFailure("1.2.3.4", T0);
    for (let i = 1; i < MAX_FAILURES; i++) recordLoginFailure("1.2.3.4", T0 + i * 1000);
    expect(checkLoginThrottle("1.2.3.4", T0 + WINDOW_MS).blocked).toBe(false);
  });
});
