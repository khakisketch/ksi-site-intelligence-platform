import { describe, expect, it } from "vitest";

import { readableApiError } from "@/lib/core-api/labels";

// coreApiErrorResponse(route-handler-util.ts)가 만드는 실패 응답 본문에는
// verdict 필드가 없다({message, code, detail}뿐이다) — 성공 응답에만 verdict 가
// 있다. 예전에는 SourceUploadPanel/ComparisonSubmitPanel 이 각자 `body.verdict`를
// 먼저 읽었는데, 실패 응답엔 그게 늘 없어서 매번 `body.detail`(Core 내부 원문,
// 예: "journal 봉인됨 — 재시작 필요")로 떨어졌다. 이미 사람 말로 옮겨 둔
// `body.message`는 한 번도 쓰이지 않았다. 이 파일은 그 회귀를 고정한다.

describe("verdict 가 없는 coreApiErrorResponse 실패 응답", () => {
  it("등록된 코드는 API_ERROR_MESSAGE 라벨을 쓴다", () => {
    const body = { code: "BUNDLE_NOT_SEALED", message: "무시돼야 할 문구", detail: "raw" };
    expect(readableApiError(body, "기본값")).toBe(
      "번들이 아직 봉인되지 않았습니다 — 업로드를 마치고 봉인한 뒤 다시 시도하세요.",
    );
  });

  it("[핵심 회귀] 등록되지 않은 코드는 detail 이 아니라 이미 사람 말로 옮겨진 message 를 쓴다", () => {
    const body = { code: "STORE_UNAVAILABLE_XYZ", message: "서버 저장소 점검 중입니다.", detail: "journal 봉인됨 — 재시작 필요" };
    expect(readableApiError(body, "기본값")).toBe("서버 저장소 점검 중입니다.");
  });

  it("message 도 없으면 detail(원문)로 물러난다", () => {
    const body = { code: "UNKNOWN_XYZ", detail: "raw core detail" };
    expect(readableApiError(body, "기본값")).toBe("raw core detail");
  });

  it("아무것도 없으면 기본값을 쓴다", () => {
    expect(readableApiError({}, "기본값")).toBe("기본값");
  });

  it("빈 문자열 message 는 내용으로 치지 않고 다음 자리로 넘어간다", () => {
    const body = { message: "", detail: "raw" };
    expect(readableApiError(body, "기본값")).toBe("raw");
  });
});

describe("verdict 가 있는 성공 경로의 거부(예: 이미 봉인됨)", () => {
  it("verdict 를 code 보다 우선한다", () => {
    const body = { verdict: "BUNDLE_SEALED", code: "SHOULD_NOT_WIN", detail: "raw" };
    expect(readableApiError(body, "기본값")).toBe(
      "이미 봉인된 번들입니다. 추가 사진을 올리려면 새 임무를 발급하세요.",
    );
  });
});
