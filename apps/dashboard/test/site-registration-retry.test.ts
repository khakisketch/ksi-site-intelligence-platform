import { describe, expect, it } from "vitest";

import {
  isRetryOfOwnSitePost,
  nextOwnPostSiteId,
} from "@/lib/site-registration/shared";

// POST /v1/sites 의 409 를 "내 재시도"로 볼지의 판정. 틀리면 저장이 일어나지
// 않았는데 "현장이 등록되었습니다"가 뜨고, 전체 위저드에서는 그 남의 현장 앞으로
// 임무 계약 발급까지 이어진다. 두 번의 독립 검토가 각각 다른 구멍을 찾았으므로
// 두 경로를 다 고정한다.
describe("현장 등록 409 재시도 판정", () => {
  const DUP = "DUPLICATE_SITE_ID";

  // ref 는 "이 세션이 보낸 것으로 쳐서 뒤이은 409 를 내 것으로 볼 siteId" 를 담는다.
  //
  // 두 위저드의 runSubmission 세 단계를 **그대로** 흉내낸다 — 순서가 곧 정확성이다:
  //   ① POST 직전: ref = siteId ("결과를 모른다"가 기본값)
  //   ② 응답이 실패면: ref = nextOwnPostSiteId(siteId, status, body.code)
  //      → 확정 409 면 여기서 비워지고, 내 재시도가 아니면 error 로 조기 return
  //   ③ 조기 return 하지 않고 내려오면(진짜 성공 or 인정된 409):
  //      ref = nextOwnPostSiteId(siteId, status, undefined)  ← 세 번째 인자 의도적
  //
  // ③ 을 빠뜨리면 "인정된 409" 경로의 최종 ref 를 잘못 계산해, 그 경로를 깨는
  // 회귀(③ 의 undefined 를 body.code 로 바꾸는 것)를 이 테스트가 못 잡는다
  // (2026-08-16 4차 독립 검토 지적).
  function attempt(
    own: string | null,
    siteId: string,
    status: number | null,
    code: string | undefined,
  ): { treatedAsOwnRetry: boolean; ownAfter: string | null } {
    const previous = own;
    let next: string | null = siteId; // ①
    if (status === null) {
      // fetch 예외 — 응답이 없으니 ①의 "모른다" 그대로, ②③ 둘 다 안 탄다
      return { treatedAsOwnRetry: false, ownAfter: next };
    }
    const ok = status >= 200 && status < 300;
    let treatedAsOwnRetry = false;
    if (!ok) {
      next = nextOwnPostSiteId(siteId, status, code); // ②
      treatedAsOwnRetry = isRetryOfOwnSitePost(previous, siteId, status, code);
      if (!treatedAsOwnRetry) {
        return { treatedAsOwnRetry: false, ownAfter: next }; // 조기 return
      }
    }
    next = nextOwnPostSiteId(siteId, status, undefined); // ③
    return { treatedAsOwnRetry, ownAfter: next };
  }

  it("첫 시도의 409 는 남의 현장이므로 실패다", () => {
    const r = attempt(null, "site-A", 409, DUP);
    expect(r.treatedAsOwnRetry).toBe(false);
  });

  it("[핵심] 남의 현장으로 409 를 받은 뒤 입력을 그대로 두고 다시 시도해도 성공이 아니다", () => {
    // 화면의 '다시 시도' 버튼은 siteId 를 바꾸지 않고 재제출한다.
    const first = attempt(null, "site-A", 409, DUP);
    expect(first.treatedAsOwnRetry).toBe(false);
    // 서버가 "이미 있다"를 확정해 줬으므로 이 시도로 만들어진 것은 없다.
    expect(first.ownAfter).toBeNull();

    const second = attempt(first.ownAfter, "site-A", 409, DUP);
    expect(second.treatedAsOwnRetry).toBe(false);
  });

  it("[핵심] 다른 siteId 로 바꿔 재시도한 409 도 성공이 아니다", () => {
    const first = attempt(null, "site-A", 500, undefined);
    // 5xx 는 서버가 처리했는지 알 수 없으므로 "모른다" 로 남는다.
    expect(first.ownAfter).toBe("site-A");

    const second = attempt(first.ownAfter, "site-B", 409, DUP);
    expect(second.treatedAsOwnRetry).toBe(false);
  });

  it("응답을 못 받은 뒤 같은 siteId 의 409 는 내 재시도로 인정한다", () => {
    // 이 판정이 존재하는 유일한 이유 — 서버는 등록했는데 응답이 유실된 경우.
    const first = attempt(null, "site-A", null, undefined);
    expect(first.ownAfter).toBe("site-A");

    const second = attempt(first.ownAfter, "site-A", 409, DUP);
    expect(second.treatedAsOwnRetry).toBe(true);
  });

  it("응답 유실이 두 번 이어져도 그 뒤의 409 는 내 재시도다", () => {
    const first = attempt(null, "site-A", null, undefined);
    const second = attempt(first.ownAfter, "site-A", null, undefined);
    expect(second.ownAfter).toBe("site-A");

    const third = attempt(second.ownAfter, "site-A", 409, DUP);
    expect(third.treatedAsOwnRetry).toBe(true);
  });

  it("409 라도 DUPLICATE_SITE_ID 가 아니면 재시도로 인정하지 않는다", () => {
    const first = attempt(null, "site-A", null, undefined);
    const second = attempt(first.ownAfter, "site-A", 409, "SOMETHING_ELSE");
    expect(second.treatedAsOwnRetry).toBe(false);
  });

  it("확정 409 만 판정 근거를 비운다 — 성공은 비우지 않는다", () => {
    // 성공은 "내가 만들었다" 이므로 뒤이은 409 는 내 것이다. 여기서 비우면
    // 전체 위저드의 '이전 → 같은 siteId 재시도' 경로가 자기 현장을 남의 것으로
    // 오판한다(아래 회귀 테스트).
    expect(nextOwnPostSiteId("site-A", 201, undefined)).toBe("site-A");
    expect(nextOwnPostSiteId("site-A", 200, undefined)).toBe("site-A");
    expect(nextOwnPostSiteId("site-A", 409, DUP)).toBeNull();
  });

  it("[회귀] 등록 성공 뒤 뒤로 갔다 같은 siteId 로 재시도하면 내 현장으로 알아본다", () => {
    // 전체 위저드 실제 경로: 1) 현장 등록 성공 → 2) 임무 계획 발급 실패 →
    // 3) 사용자가 '이전'(handleBack 이 siteRegisteredRef 만 되돌린다) →
    // 4) 같은 siteId 로 재-POST → 409(내가 1)에서 만든 그 현장).
    const created = attempt(null, "site-A", 201, undefined);
    expect(created.ownAfter).toBe("site-A");

    const afterBack = attempt(created.ownAfter, "site-A", 409, DUP);
    expect(afterBack.treatedAsOwnRetry).toBe(true);
  });

  it("[회귀] 등록 성공 뒤 siteId 를 남의 것으로 바꿔 오면 여전히 실패다", () => {
    const created = attempt(null, "site-A", 201, undefined);
    const other = attempt(created.ownAfter, "site-B", 409, DUP);
    expect(other.treatedAsOwnRetry).toBe(false);
  });

  it("[회귀] 인정된 409 뒤에도 소유권이 유지돼 다음 409 도 내 것이다", () => {
    // 응답 유실 → 같은 siteId 409(인정) → 또 뒤로 갔다 같은 siteId 409.
    // 컴포넌트 ③단계가 `undefined` 를 넘기지 않고 실제 code 를 넘기면 인정 직후
    // ref 가 비워져, 이 세 번째 시도가 "남의 현장"으로 뒤집힌다.
    const lost = attempt(null, "site-A", null, undefined);
    expect(lost.ownAfter).toBe("site-A");

    const recognized = attempt(lost.ownAfter, "site-A", 409, DUP);
    expect(recognized.treatedAsOwnRetry).toBe(true);
    expect(recognized.ownAfter).toBe("site-A"); // ③ 이 소유권을 되살린다

    const again = attempt(recognized.ownAfter, "site-A", 409, DUP);
    expect(again.treatedAsOwnRetry).toBe(true);
  });
});
