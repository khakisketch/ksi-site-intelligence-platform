import "server-only";

/**
 * 로그인 시도 제한 (risk dashboard-login-residual-hardening).
 *
 * 이 제품의 인증은 **bearer 토큰 하나**다. 사용자명·비밀번호 조합이 아니라
 * 단일 비밀이므로, 네트워크로 포트에 닿는 누구나 무제한으로 추측할 수 있으면
 * 전체 보안이 토큰 엔트로피 하나에만 걸린다. dev 토큰이 추측 가능한 리터럴
 * (`dev-admin-token`)이라는 점이 그 위험을 실물로 보여준다.
 *
 * ## 프로세스 메모리에 둔다
 *
 * 현장 서버는 단일 인스턴스 배포다(ADR-KSI-005 — 오프라인 우선, 현장 1대).
 * 공유 저장소를 끌어들이면 오프라인에서 인증이 외부 의존을 갖게 되는데, 그건
 * 이 제품이 피하려는 바로 그 구조다. **다중 인스턴스로 가면 이 구현은 무의미해진다**
 * (각 인스턴스가 자기 카운터만 본다) — 그때는 공유 카운터가 필요하다.
 *
 * ## 성공은 리셋한다
 *
 * 정상 운영자가 오타를 몇 번 낸 뒤 성공하면 카운터가 남지 않아야 한다. 잠금이
 * 정상 사용을 방해하기 시작하면 운영자는 우회로를 찾는다(토큰 공유·메모).
 *
 * ## 감수한 것: 차단 중에는 올바른 토큰도 막힌다
 *
 * 키가 IP 라서, 같은 출구 IP 를 쓰는 정상 운영자가 남의 실패 때문에 잠길 수 있다.
 * 인증 단위가 계정이 아니라 **토큰 하나**라 "이 사용자만 잠근다"가 성립하지 않기
 * 때문이다. 창을 5분으로 짧게 둔 것이 그 절충이고, 현장 서버가 사내망이라는 배포
 * 전제(ADR-KSI-010 §2)가 이 선택을 지탱한다 — 같은 망에 공격자가 있다면 그건
 * 이 제한으로 해결할 문제가 아니다. 계정별 인증을 도입하면 키를 계정으로 바꾼다.
 */

/** 창 안에서 허용할 실패 횟수. 넘으면 창이 끝날 때까지 거부한다. */
const MAX_FAILURES = 8;
/** 실패 카운트 창(ms). */
const WINDOW_MS = 5 * 60_000;

interface Attempt {
  failures: number;
  /** 창 시작 시각 — 이 시점부터 WINDOW_MS 가 지나면 카운터를 버린다. */
  windowStart: number;
}

const attempts = new Map<string, Attempt>();

/** 메모리 누수 방지 — 창이 지난 항목은 다음 접근 때 버린다. */
function current(key: string, now: number): Attempt | undefined {
  const entry = attempts.get(key);
  if (entry === undefined) return undefined;
  if (now - entry.windowStart >= WINDOW_MS) {
    attempts.delete(key);
    return undefined;
  }
  return entry;
}

export interface ThrottleState {
  blocked: boolean;
  /** 차단이 풀리기까지 남은 초 — 사용자에게 "얼마나 기다려야 하는지" 말해준다. */
  retryAfterSeconds: number;
}

export function checkLoginThrottle(key: string, now: number = Date.now()): ThrottleState {
  const entry = current(key, now);
  if (entry === undefined || entry.failures < MAX_FAILURES) {
    return { blocked: false, retryAfterSeconds: 0 };
  }
  const remaining = WINDOW_MS - (now - entry.windowStart);
  return { blocked: true, retryAfterSeconds: Math.max(1, Math.ceil(remaining / 1000)) };
}

export function recordLoginFailure(key: string, now: number = Date.now()): void {
  const entry = current(key, now);
  if (entry === undefined) {
    attempts.set(key, { failures: 1, windowStart: now });
    return;
  }
  entry.failures += 1;
}

export function recordLoginSuccess(key: string): void {
  attempts.delete(key);
}

/** 테스트 전용 — 모듈 상태를 비운다. */
export function resetLoginThrottle(): void {
  attempts.clear();
}

export const LOGIN_THROTTLE_LIMITS = { MAX_FAILURES, WINDOW_MS } as const;
