import { describe, expect, it } from "vitest";

import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";

// CSRF 2차 방어선. 여기는 독립 재검토에서 **두 번** 고쳐진 자리다 —
// ①원래 인증만 있고 Origin 검사가 없었고(P2-F 1차) ②그 다음 nextUrl.origin 을
// 기준으로 삼았다가 Next 가 127.0.0.1 을 localhost 로 정규화하는 바람에 정상
// same-origin 요청까지 403 되는 회귀가 났다(P2-F 2차). 두 실패 모두 타입체크로는
// 안 보인다 — 그래서 여기 고정한다.

function request(headers: Record<string, string>): Parameters<typeof isCrossSiteMutation>[0] {
  const map = new Map(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
  return { headers: { get: (name: string) => map.get(name.toLowerCase()) ?? null } } as Parameters<
    typeof isCrossSiteMutation
  >[0];
}

describe("동일 출처 판정", () => {
  it("Origin 의 host 가 Host 헤더와 같으면 통과한다", () => {
    expect(
      isCrossSiteMutation(request({ origin: "http://127.0.0.1:3000", host: "127.0.0.1:3000" })),
    ).toBe(false);
  });

  it("127.0.0.1 접속을 localhost 로 정규화해 막지 않는다 — 실제 회귀 사례", () => {
    // nextUrl.origin 을 기준으로 쓰면 이 요청이 cross-site 로 판정됐다.
    expect(
      isCrossSiteMutation(request({ origin: "http://127.0.0.1:3000", host: "127.0.0.1:3000" })),
    ).toBe(false);
  });

  it("다른 출처는 차단한다", () => {
    expect(
      isCrossSiteMutation(request({ origin: "https://evil.example", host: "127.0.0.1:3000" })),
    ).toBe(true);
  });

  it("포트가 다르면 다른 출처다", () => {
    expect(
      isCrossSiteMutation(request({ origin: "http://127.0.0.1:3100", host: "127.0.0.1:3000" })),
    ).toBe(true);
  });

  it("리버스 프록시 뒤에서는 x-forwarded-host 가 Host 보다 우선한다", () => {
    expect(
      isCrossSiteMutation(
        request({
          origin: "https://ksi.example",
          host: "internal-upstream:8080",
          "x-forwarded-host": "ksi.example",
        }),
      ),
    ).toBe(false);
  });

  it("x-forwarded-host 가 여러 값이면 첫 번째(원 클라이언트)를 쓴다", () => {
    expect(
      isCrossSiteMutation(
        request({
          origin: "https://ksi.example",
          host: "internal:8080",
          "x-forwarded-host": " ksi.example , proxy.internal ",
        }),
      ),
    ).toBe(false);
  });
});

describe("Origin 헤더가 없을 때", () => {
  it("Sec-Fetch-Site 로 폴백한다", () => {
    expect(isCrossSiteMutation(request({ "sec-fetch-site": "same-origin" }))).toBe(false);
    expect(isCrossSiteMutation(request({ "sec-fetch-site": "none" }))).toBe(false);
    expect(isCrossSiteMutation(request({ "sec-fetch-site": "cross-site" }))).toBe(true);
    expect(isCrossSiteMutation(request({ "sec-fetch-site": "same-site" }))).toBe(true);
  });

  it("둘 다 없으면 거부하지 않는다 — 세션 검증이 1차 방어선이고 여기는 defense-in-depth 다", () => {
    expect(isCrossSiteMutation(request({}))).toBe(false);
  });
});

describe("비정상 입력", () => {
  it("파싱 불가한 Origin 은 차단한다 — 정상 브라우저는 만들지 않는 형태다", () => {
    expect(isCrossSiteMutation(request({ origin: "not a url", host: "127.0.0.1:3000" }))).toBe(true);
  });

  it("Origin 은 있는데 Host 가 없으면 거부하지 않는다", () => {
    expect(isCrossSiteMutation(request({ origin: "http://127.0.0.1:3000" }))).toBe(false);
  });
});
