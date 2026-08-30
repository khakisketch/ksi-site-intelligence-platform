import { describe, expect, it } from "vitest";

import {
  assignUniqueMediaIds,
  canReissueProcessingJob,
  chunk,
  deriveMediaId,
  isTerminalJobStatus,
  summarizeUploadBatch,
} from "@/lib/source-upload";
import type { SourceMediaItemResultView } from "@/lib/core-api/types";

// ═══════════════════════════════════════════════════════════════════════════
// mediaId 유도 골든 — **두 구현이 이 표를 함께 만족해야 한다.**
//
//   수동 경로  apps/dashboard/src/lib/source-upload.ts :: deriveMediaId
//   자동 경로  edge/manifold-runtime/.../media_offload.cpp :: DeriveMediaId
//
// 같은 사진이 두 경로로 들어올 수 있고(ADR-KSI-013 — 기체 자동 회수가 주 경로,
// SD카드 수동이 상시 보존 경로), 두 경로가 같은 사진에 다른 mediaId 를 붙이면
// 서버 번들에 같은 장이 두 번 쌓인다. 그 번들의 digest 는 그 순간 실제로 찍은
// 장수를 거짓으로 말하게 된다.
//
// 규약은 **"원본 파일명 − 확장자"** 한 줄이고, 아래 표가 그 한 줄의 정확한 뜻이다.
// 표를 고치려면 양쪽 구현과 양쪽 시험을 함께 고쳐야 한다.
//
// 유도 결과는 Core 의 PATH_SAFE_IDENTIFIER_PATTERN
// (^[A-Za-z0-9][A-Za-z0-9_.-]*$, services/core/src/ksi_core/identifiers.py)을
// 반드시 만족해야 한다 — 안 그러면 등록 자체가 서버에서 거부된다.
// ═══════════════════════════════════════════════════════════════════════════

const CORE_IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

const MEDIA_ID_GOLDEN: Array<[input: string, expected: string, why: string]> = [
  ["DJI_0001.JPG", "DJI_0001", "DJI 기본 파일명 — 확장자만 떨어진다"],
  ["DJI_0001.jpg", "DJI_0001", "확장자 대소문자는 결과에 영향을 주지 않는다"],
  ["DJI_0001.DNG", "DJI_0001", "RAW 도 같은 mediaId 가 된다(알려진 한계 — 아래 시험 참조)"],
  ["DJI_20260816120000_0042_D.JPG", "DJI_20260816120000_0042_D", "긴 DJI 파일명도 그대로"],
  ["noextension", "noextension", "확장자가 없으면 이름 전체가 mediaId 다"],
  ["a.b.jpg", "a.b", "마지막 점만 확장자다 — 중간 점은 이름의 일부"],
  [".hidden", "hidden", "첫 글자의 점은 확장자가 아니다 — 다만 Core 첫 글자 규칙에 걸려 제거된다"],
  ["사진 001 (1).jpg", "001-1-", "허용 밖 연속 구간은 하이픈 하나 + 선행 비영숫자 제거"],
  ["__leading.jpg", "leading", "선행 비영숫자 구간을 제거한다(Core 첫 글자 규칙)"],
  ["！！！.jpg", "media", "유도 결과가 비면 media 로 대체한다"],
  ["!!!", "media", "확장자도 없고 남는 것도 없는 경우"],
];

describe("deriveMediaId — 자동/수동 공통 골든", () => {
  it.each(MEDIA_ID_GOLDEN)("%s → %s (%s)", (input, expected) => {
    expect(deriveMediaId(input)).toBe(expected);
  });

  it("모든 골든 출력이 Core 식별자 규칙을 만족한다", () => {
    for (const [, expected] of MEDIA_ID_GOLDEN) {
      expect(CORE_IDENTIFIER_PATTERN.test(expected), `${expected} 가 규칙을 벗어난다`).toBe(true);
    }
  });

  it("120자로 자른다 — 자른 뒤에도 식별자 규칙을 지킨다", () => {
    const result = deriveMediaId("a".repeat(200) + ".jpg");
    expect(result.length).toBe(120);
    expect(CORE_IDENTIFIER_PATTERN.test(result)).toBe(true);
  });

  it("같은 사진의 자동/수동 파일명이 같으면 mediaId 도 같다 — 이 규약의 존재 이유", () => {
    // 자동 경로는 PSDK 파일 목록에서, 수동 경로는 브라우저 File.name 에서 이름을
    // 받는다. 확장자 표기(JPG/jpg/JPEG)가 갈려도 mediaId 는 같아야 한다.
    expect(deriveMediaId("DJI_0007.JPG")).toBe(deriveMediaId("DJI_0007.jpeg"));
  });

  it("NFC/NFD 경계 — 이 함수 자체는 normalize(NFC) 를 먼저 걸어 두 정규화 형태를 하나로 모은다", () => {
    // 화면에는 똑같이 보이는 두 형태(완성형 e-acute 1 코드포인트 vs 자모분리형
    // e + 결합 억음부호 2 코드포인트)가 여기서는 같은 mediaId 가 된다.
    // \u 이스케이프로 명시 — 소스에 두 형태를 직접 타이핑하면 저장 시점에
    // 편집기가 조용히 한쪽으로 정규화할 위험이 있다.
    const precomposed: string = "café.jpg"; // U+00E9
    const decomposed: string = "café.jpg"; // U+0065 U+0301
    expect(precomposed === decomposed).toBe(false); // 서로 다른 문자열이라는 전제 확인
    expect(deriveMediaId(precomposed)).toBe("caf-");
    expect(deriveMediaId(decomposed)).toBe("caf-");
    // **주의**: 이 동치는 TypeScript 안에서만 보장된다. C++ 쪽 DeriveMediaId 는
    // NFC 정규화를 하지 않아서 완성형은 "caf-", 자모분리형은 "cafe-" 로 갈린다
    // (edge_runtime_tests.cpp 의 NFC/NFD 경계 시험, media_offload.hpp 상단
    // 주석) — 두 구현의 동치는 카메라 원본 파일명처럼 ASCII 인 경우로 한정된다.
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// mediaId 충돌 접미사 골든 — **두 구현이 이 표를 함께 만족해야 한다.**
//
//   수동 경로  apps/dashboard/src/lib/source-upload.ts     :: assignUniqueMediaIds
//   자동 경로  edge/manifold-runtime/.../media_offload.cpp :: AssignMediaIds
//
// 접미사는 카메라 원본 파일명(확장자 포함) 문자열 자체의 sha256 앞 8 hex다
// (파일 바이트가 아니다) — 그래서 선택 순서·목록 순서와 무관하다. 아래 값은
// Node crypto·Python hashlib·이 파일의 Sha256Digest(C++) 세 구현으로 각각
// 계산해 손으로 대조했다. edge_runtime_tests.cpp 의 media_id_assign_golden 과
// **같은 표**다 — 한쪽만 고치면 이 vitest 나 저쪽 ctest 중 하나가 반드시 깨진다.
// ═══════════════════════════════════════════════════════════════════════════
const MEDIA_ID_ASSIGN_GOLDEN: Array<[names: string[], expected: string[], why: string]> = [
  [["DJI_0001.JPG", "DJI_0002.JPG"], ["DJI_0001", "DJI_0002"], "충돌 없음 — 접미사 없이 그대로"],
  [
    ["DJI_0001.JPG", "DJI_0001.DNG"],
    ["DJI_0001-1bb98f97", "DJI_0001-4dbbd212"],
    "2건 충돌 — RAW+JPEG 동시 저장",
  ],
  [
    ["DJI_0002.JPG", "DJI_0002.DNG", "DJI_0002.RAW"],
    ["DJI_0002-4dce79c7", "DJI_0002-f17a8db3", "DJI_0002-f7bbac27"],
    "3건 이상 충돌 — RAW+JPEG+독자 포맷 동시 저장",
  ],
  [
    ["DJI_0003.jpg", "DJI_0003.JPG"],
    ["DJI_0003-4a4d0317", "DJI_0003-e48ae859"],
    "확장자 대소문자만 다른 충돌",
  ],
  [
    ["사진.jpg", "사진.png"],
    ["media-a3b204f6", "media-66df4728"],
    "비ASCII 파일명 충돌 — 둘 다 media 로 무너진 뒤 갈라진다",
  ],
];

describe("assignUniqueMediaIds", () => {
  it("충돌 없으면 유도만 적용한다", async () => {
    await expect(assignUniqueMediaIds(["a.jpg", "b.jpg"])).resolves.toEqual(["a", "b"]);
  });

  it.each(MEDIA_ID_ASSIGN_GOLDEN)("%j → %j (%s)", async (names, expected) => {
    await expect(assignUniqueMediaIds(names)).resolves.toEqual(expected);
  });

  it("선택 순서를 바꿔도 파일별 mediaId 는 그대로다 — 재업로드 시 같은 사진이 다른 id를 받지 않는다", async () => {
    // 교차 트랙 결함의 핵심 — 예전에는 선택 순서로 -2/-3 을 매겨서, 같은 두
    // 파일을 반대 순서로 선택하면 JPG 와 DNG 의 mediaId 가 서로 바뀌었다.
    const forward = await assignUniqueMediaIds(["DJI_0001.JPG", "DJI_0001.DNG"]);
    const reversed = await assignUniqueMediaIds(["DJI_0001.DNG", "DJI_0001.JPG"]);
    expect(forward).not.toBeNull();
    expect(reversed).not.toBeNull();
    // DJI_0001.JPG 는 어느 자리에 있든 같은 id, DNG 도 마찬가지.
    expect(reversed![0]).toBe(forward![1]);
    expect(reversed![1]).toBe(forward![0]);
  });

  it("완전히 같은 파일명이 두 번 나오면 값을 지어내지 않고 거부한다(null)", async () => {
    // 해시 접미사는 이름 자체의 함수라, 완전히 같은 이름 두 개는 어떤 접미사를
    // 붙여도 갈라지지 않는다 — AssignMediaIds(C++) 가 false 를 돌려주는 것과
    // 같은 경계다.
    await expect(assignUniqueMediaIds(["DJI_0001.JPG", "DJI_0001.JPG"])).resolves.toBeNull();
  });

  it("빈 파일명이 섞이면 거부한다(null)", async () => {
    await expect(assignUniqueMediaIds([""])).resolves.toBeNull();
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

describe("canReissueProcessingJob", () => {
  it("FAILED/CANCELLED 종료 작업만 발행 권한으로 새 작업을 만들 수 있다", () => {
    expect(canReissueProcessingJob("FAILED", true)).toBe(true);
    expect(canReissueProcessingJob("CANCELLED", true)).toBe(true);
    expect(canReissueProcessingJob("SUCCEEDED", true)).toBe(false);
    expect(canReissueProcessingJob("RUNNING", true)).toBe(false);
    expect(canReissueProcessingJob("FAILED", false)).toBe(false);
    expect(canReissueProcessingJob(null, true)).toBe(false);
  });
});
