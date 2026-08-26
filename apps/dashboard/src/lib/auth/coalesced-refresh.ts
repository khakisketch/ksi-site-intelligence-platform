import "server-only";

/**
 * 같은 Auth.js JWT를 여러 서버 요청이 동시에 갱신하지 않도록 합친다.
 *
 * OIDC provider가 refresh-token rotation을 사용하면 동일 token의 두 번째
 * 요청은 정상적으로 invalid_grant가 된다. 이 map은 token 값을 외부로
 * 내보내지 않고 Dashboard 프로세스 안에서만 잠시 보관한다.
 */
interface CoalescedRefreshGlobal {
  __ksiAuthRefreshRequests?: Map<string, Promise<unknown>>;
}

// Next.js는 같은 서버 프로세스에서도 Auth.js를 Route Handler와 Server Component의
// 서로 다른 bundle에서 평가할 수 있다. module-local map이면 두 bundle이 같은 1회용
// refresh token을 각각 교환한다. process global registry로 묶어 같은 JS realm의 모든
// 인증 진입점이 동일한 single-flight와 짧은 재사용 창을 공유하게 한다.
const refreshGlobal = globalThis as typeof globalThis & CoalescedRefreshGlobal;
const inFlight = refreshGlobal.__ksiAuthRefreshRequests ??= new Map<string, Promise<unknown>>();

interface CoalescedRefreshOptions {
  /**
   * 회전 직후에도 이전 JWT cookie를 가진 후발 요청이 도착할 수 있다. 성공한 결과를
   * 이 시간만큼 유지하면 같은 1회용 refresh token을 provider에 다시 보내지 않는다.
   */
  reuseForMs?: number;
}

export function coalescedRefresh<T>(
  key: string,
  operation: () => Promise<T>,
  options: CoalescedRefreshOptions = {},
): Promise<T> {
  const existing = inFlight.get(key);
  if (existing) return existing as Promise<T>;

  const promise = operation();
  inFlight.set(key, promise);
  const clearNow = () => {
    if (inFlight.get(key) === promise) inFlight.delete(key);
  };
  const clearAfterReuseWindow = () => {
    const reuseForMs = Math.max(0, options.reuseForMs ?? 0);
    if (reuseForMs === 0) {
      clearNow();
      return;
    }
    globalThis.setTimeout(clearNow, reuseForMs);
  };
  // 성공한 회전 결과는 짧게 재사용한다. rejection은 즉시 지워 다음 요청이
  // 일시적 provider 실패에서 복구할 수 있게 한다.
  void promise.then(clearAfterReuseWindow, clearNow);
  return promise;
}
