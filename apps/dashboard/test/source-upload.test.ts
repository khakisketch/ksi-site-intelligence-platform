import { describe, expect, it } from "vitest";

import {
  assignUniqueMediaIds,
  chunk,
  isTerminalJobStatus,
  sanitizeMediaId,
  summarizeUploadBatch,
} from "@/lib/source-upload";
import type { SourceMediaItemResultView } from "@/lib/core-api/types";

// PATH_SAFE_IDENTIFIER_PATTERN(services/core/src/ksi_core/identifiers.py)과
// 클라이언트 정제가 갈리면 등록 자체가 서버에서 거부된다 — 이 테스트가 그
// 규칙을 고정한다.

describe("sanitizeMediaId", () => {
  it("영숫자·언더스코어·점·하이픈은 그대로 둔다", () => {
    expect(sanitizeMediaId("DJI_0001.JPG")).toBe("DJI_0001.JPG");
  });

  it("허용되지 않는 문자(한글·공백·괄호)를 하이픈으로 치환한다", () => {
    const result = sanitizeMediaId("사진 001 (1).jpg");
    expect(result).toBe("001-1-.jpg");
    expect(/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(result)).toBe(true);
  });

  it("영숫자로 시작하지 않으면 선행 비영숫자 구간을 제거한다", () => {
    expect(sanitizeMediaId("__leading.jpg")).toBe("leading.jpg");
  });

  it("정제 후 완전히 비면 media 로 대체한다", () => {
    expect(sanitizeMediaId("！！！")).toBe("media");
  });

  it("120자로 자른다", () => {
    const long = "a".repeat(200) + ".jpg";
    expect(sanitizeMediaId(long).length).toBe(120);
  });
});

describe("assignUniqueMediaIds", () => {
  it("충돌 없으면 정제만 적용한다", () => {
    expect(assignUniqueMediaIds(["a.jpg", "b.jpg"])).toEqual(["a.jpg", "b.jpg"]);
  });

  it("정제 후 같은 이름이 되는 파일들을 결정론적으로 갈라놓는다", () => {
    const result = assignUniqueMediaIds(["a?.jpg", "a!.jpg", "a.jpg"]);
    expect(new Set(result).size).toBe(3);
    expect(result[0]).toBe("a-.jpg");
    expect(result[1]).toBe("a-.jpg-2");
    expect(result[2]).toBe("a.jpg");
  });
});

describe("chunk", () => {
  it("정확히 나누어떨어지면 균등 분할한다", () => {
    expect(chunk([1, 2, 3, 4], 2)).toEqual([[1, 2], [3, 4]]);
  });

  it("나머지는 마지막 묶음에 남는다", () => {
    expect(chunk([1, 2, 3], 2)).toEqual([[1, 2], [3]]);
  });

  it("빈 배열은 빈 결과다", () => {
    expect(chunk([], 5)).toEqual([]);
  });
});

function item(overrides: Partial<SourceMediaItemResultView>): SourceMediaItemResultView {
  return {
    mediaId: "m1",
    verdict: "REGISTERED",
    objectKey: "sites/s/missions/m/source/m1",
    uploadUrl: "https://storage.example/put",
    expiresAt: "2026-01-01T00:00:00Z",
    detail: null,
    ...overrides,
  };
}

describe("summarizeUploadBatch", () => {
  it("REGISTERED + uploadUrl 은 ready 로 간다", () => {
    const summary = summarizeUploadBatch([item({})]);
    expect(summary.ready).toEqual([{ mediaId: "m1", uploadUrl: "https://storage.example/put" }]);
    expect(summary.failed).toEqual([]);
  });

  it("CLAIM_CONFLICT 는 failed 로 간다", () => {
    const summary = summarizeUploadBatch([
      item({ verdict: "CLAIM_CONFLICT", uploadUrl: null, detail: "다른 내용으로 이미 등록됨" }),
    ]);
    expect(summary.ready).toEqual([]);
    expect(summary.failed).toEqual([
      { mediaId: "m1", verdict: "CLAIM_CONFLICT", detail: "다른 내용으로 이미 등록됨" },
    ]);
  });

  it("REGISTERED 인데 uploadUrl 이 없으면(계약상 이례) failed 로 안전하게 분류한다", () => {
    const summary = summarizeUploadBatch([item({ uploadUrl: null })]);
    expect(summary.ready).toEqual([]);
    expect(summary.failed).toHaveLength(1);
  });

  it("여러 건을 섞으면 각자 맞는 쪽으로 간다", () => {
    const summary = summarizeUploadBatch([
      item({ mediaId: "ok1" }),
      item({ mediaId: "bad1", verdict: "UNSUPPORTED_CONTENT_TYPE", uploadUrl: null }),
      item({ mediaId: "ok2" }),
    ]);
    expect(summary.ready.map((r) => r.mediaId)).toEqual(["ok1", "ok2"]);
    expect(summary.failed.map((f) => f.mediaId)).toEqual(["bad1"]);
  });
});

describe("isTerminalJobStatus", () => {
  it("QUEUED/RUNNING 은 진행 중이다(false)", () => {
    expect(isTerminalJobStatus("QUEUED")).toBe(false);
    expect(isTerminalJobStatus("RUNNING")).toBe(false);
  });

  it("SUCCEEDED/FAILED/CANCELLED 는 종료 상태다(true)", () => {
    expect(isTerminalJobStatus("SUCCEEDED")).toBe(true);
    expect(isTerminalJobStatus("FAILED")).toBe(true);
    expect(isTerminalJobStatus("CANCELLED")).toBe(true);
  });
});
