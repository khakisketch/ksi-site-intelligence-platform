// 현장 화면의 인증 분기 — **리다이렉트하지 않고 화면 안에서 처리한다.**
//
// 다른 화면은 proxy.ts 가 세션 쿠키 부재를 보고 /login 으로 302 를 준다. /field 는
// 그 경로에서 빠져 있다(proxy.ts 주석): Pilot 2 서드파티 클라우드 웹뷰가 302 를
// 따라간다는 보장이 없고, 삼키는 경우 화면이 빈 채로 멈춘다. 현장에서 그건 "앱이
// 죽었다"로 읽히고, 그 순간 운영자에게는 복구 수단이 없다.
//
// 그래서 /field 는 **세션 실패를 화면 상태로** 다룬다. 이 모듈은 그 판정만 갖는다
// (순수 함수 — vitest 대상. Core 호출·쿠키 접근은 페이지가 한다).

/** whoAmI 가 실패한 사유를 화면이 아는 형태로 좁힌 것. */
export type FieldSessionFailure =
  /** 세션 쿠키 자체가 없다 — 아직 아무도 로그인하지 않았거나 로그아웃 직후. */
  | { kind: "no-session" }
  /** Core 가 응답은 했다 — 상태코드가 사유다. */
  | { kind: "api"; status: number }
  /** Core 에 닿지 못했다(네트워크·DNS·TLS). 로그인으로 풀리지 않는다. */
  | { kind: "unreachable" };

export type FieldSessionVerdict =
  /**
   * 인라인 로그인 폼을 보여준다. `notice` 는 폼 위에 띄울 사유 한 줄이며,
   * null 이면 아무 사유도 붙이지 않는다 — 첫 방문에 "세션이 만료되었습니다"를
   * 띄우면 그건 거짓말이고, 운영자는 있지도 않던 세션을 찾게 된다.
   */
  | { kind: "login"; notice: string | null }
  /** 로그인으로 풀리지 않는 실패 — 폼을 보여주면 안 된다(누르면 또 실패한다). */
  | { kind: "error"; message: string };

/**
 * 실패 사유 → 화면이 할 일.
 *
 * 판정의 요점은 **"다시 로그인하면 풀리는가"** 하나다. 그것만이 인라인 폼을
 * 정당화한다. 서버가 죽어서 실패한 자리에 로그인 폼을 놓으면 운영자는 토큰을
 * 몇 번이고 다시 입력하며 자기 잘못을 찾는다.
 */
export function classifyFieldSessionFailure(failure: FieldSessionFailure): FieldSessionVerdict {
  if (failure.kind === "no-session") {
    return { kind: "login", notice: null };
  }
  if (failure.kind === "unreachable") {
    return {
      kind: "error",
      message: "서버에 연결하지 못했습니다. 통신 상태를 확인한 뒤 다시 여세요.",
    };
  }

  if (failure.status === 401) {
    return { kind: "login", notice: "세션이 만료되었습니다. 다시 로그인하세요." };
  }
  if (failure.status === 403) {
    // 조종기는 공용 장비다 — 앞사람 계정이 남아 있을 수 있다. 이 실패는 "권한
    // 없음"이지만 현장에서의 해법은 대개 **다른 계정으로 다시 로그인**이다.
    return {
      kind: "login",
      notice: "지금 로그인된 계정에는 이 화면을 볼 권한이 없습니다. 다른 계정으로 로그인하세요.",
    };
  }
  return {
    kind: "error",
    message: "서버가 로그인 상태를 확인해 주지 못했습니다. 잠시 후 다시 여세요.",
  };
}
