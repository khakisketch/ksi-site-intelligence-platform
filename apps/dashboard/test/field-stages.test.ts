import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  deriveFieldStages,
  deriveFlightStart,
  groupFieldMissions,
  type FieldMediaInput,
  type FieldStageInput,
} from "@/app/field/field-stages";
import { deriveMissionStages, stageBadgeTone } from "@/components/missions/MissionLifecycle";
import { MISSION_EXECUTION_STATUSES } from "@/lib/core-api/types";
import type {
  MissionExecutionStatus,
  MissionExecutionView,
  MissionRecordResponse,
  SourceMediaBundleView,
} from "@/lib/core-api/types";

function execution(status: MissionExecutionStatus, updatedAt: string | null = null): MissionExecutionView {
  return { missionId: "m-1", status, updatedAt, updatedBy: null, detail: null, history: [] };
}

function bundle(overrides: Partial<SourceMediaBundleView> = {}): SourceMediaBundleView {
  return {
    missionId: "m-1",
    status: "OPEN",
    mediaCount: 0,
    sourceBundleDigest: null,
    sealedAt: null,
    verifiedAt: null,
    lastMismatchAt: null,
    groundControlCrs: null,
    groundControlSha256: null,
    ...overrides,
  };
}

function input(overrides: Partial<FieldStageInput> = {}): FieldStageInput {
  return {
    artifactKind: "pair",
    execution: null,
    media: { kind: "not-registered" },
    coverage: { kind: "not-reported" },
    ...overrides,
  };
}

/** deriveMissionStages 가 필요로 하는 나머지 입력 — 이 파일의 시험은 실행 상태만 바꾼다. */
function missionLifecycleInput(execution: MissionExecutionView | null) {
  return {
    execution,
    coverage: { kind: "not-reported" as const },
    bundle: null,
    latestJob: null,
    hasComparisonReport: false,
  };
}

describe("4단 구조", () => {
  it("순서가 현장에서 일이 벌어지는 순서와 같다", () => {
    const stages = deriveFieldStages(input());
    expect(stages.map((s) => s.key)).toEqual(["route", "flight", "media", "result"]);
    expect(stages.map((s) => s.title)).toEqual(["경로 확보", "비행", "사진 회수", "결과"]);
  });
});

describe("① 경로 확보", () => {
  it("서버가 실행 상태를 모르면 아무것도 단정하지 않고 수동 경로로 보낸다", () => {
    const [route] = deriveFieldStages(input({ execution: null }));
    expect(route.auto.label).toBe("확인 불가");
    expect(route.auto.tone).toBe("neutral");
    expect(route.auto.detail).toContain("수동");
  });

  it("발급만 된 임무를 전달됨으로 보여주지 않는다", () => {
    const [route] = deriveFieldStages(input({ execution: execution("ISSUED") }));
    expect(route.auto.tone).toBe("neutral");
    expect(route.auto.detail).toContain("아직 기체로 전달되지 않았");
  });

  it("기체가 확인한 임무는 진행 색을 준다 — /missions 의 실행 단계와 같은 색이다", () => {
    expect(deriveFieldStages(input({ execution: execution("DISPATCHED") }))[0].auto.tone).toBe("progress");
    expect(deriveFieldStages(input({ execution: execution("ACTIVATED") }))[0].auto.tone).toBe("progress");
  });

  it("취소된 임무는 배지 색이 아니라 문장으로 막는다 — '비행하지 마세요'는 항상 남는다", () => {
    // 배지 톤 자체는 /missions(MissionLifecycle) 기준(대기→neutral)을 따른다 — 아래
    // "톤이 갈리지 않는다" 교차 시험 참조. 안전 문구는 톤과 무관하게 detail 이 낸다.
    const [route] = deriveFieldStages(input({ execution: execution("CANCELLED") }));
    expect(route.auto.detail).toContain("비행하지 마세요");
  });

  it("실행 상태의 배지 톤이 /missions(MissionLifecycle::deriveMissionStages)와 갈리지 않는다", () => {
    // 같은 MissionExecutionStatus 가 화면마다 다른 색으로 보이면 운영자는 두 화면을
    // 다른 사실로 읽는다(예전 결함: 같은 ACTIVATED 가 /missions 진행 중·/field 완료).
    // 갈리면 field-stages.ts 쪽을 맞춘다 — /missions 가 이미 사용자가 보는 기준이다.
    for (const status of MISSION_EXECUTION_STATUSES) {
      const fieldTone = deriveFieldStages(input({ execution: execution(status) }))[0].auto.tone;
      const missionTone = stageBadgeTone(deriveMissionStages(missionLifecycleInput(execution(status)))[1].tone);
      expect(fieldTone, status).toBe(missionTone);
    }
    const fieldToneUnknown = deriveFieldStages(input({ execution: null }))[0].auto.tone;
    const missionToneUnknown = stageBadgeTone(deriveMissionStages(missionLifecycleInput(null))[1].tone);
    expect(fieldToneUnknown).toBe(missionToneUnknown);
  });

  it("배지가 대표하는 사실의 시각을 실행 이력의 updatedAt 그대로 낸다", () => {
    const [route] = deriveFieldStages(
      input({ execution: execution("DISPATCHED", "2026-08-16T02:04:00Z") }),
    );
    expect(route.auto.updatedAt).toBe("2026-08-16T02:04:00Z");
  });

  it("실행 상태를 모르면 시각도 지어내지 않는다", () => {
    const [route] = deriveFieldStages(input({ execution: null }));
    expect(route.auto.updatedAt).toBeFalsy();
  });

  it("수동 경로는 자동 상태와 무관하게 항상 문구를 갖는다", () => {
    for (const status of MISSION_EXECUTION_STATUSES) {
      const [route] = deriveFieldStages(input({ execution: execution(status) }));
      expect(route.manual, `${status} 에서 수동 경로 문구가 비었다`).toBeTruthy();
    }
    expect(deriveFieldStages(input({ execution: null }))[0].manual).toBeTruthy();
  });

  it("계약 단독 발급은 내려받을 파일이 없다는 사실을 수동 경로 자리에서 말한다", () => {
    const [route] = deriveFieldStages(input({ artifactKind: "contract" }));
    expect(route.manual).toContain("계약만 발급");
  });
});

describe("② 비행", () => {
  it("완료 보고 전에는 어떤 상태에서도 비행 중이라고 말하지 않는다", () => {
    for (const status of ["ISSUED", "DISPATCHED", "ACTIVATED"] as const) {
      const flight = deriveFieldStages(input({ execution: execution(status) }))[1];
      expect(flight.auto.label).toBe("보고 없음");
      expect(flight.auto.tone).toBe("neutral");
      expect(flight.auto.detail).toContain("비행 중 상태를 받지 않습니다");
    }
  });

  it("완료 보고가 있으면 그것만 말한다", () => {
    const flight = deriveFieldStages(input({ execution: execution("COMPLETED") }))[1];
    expect(flight.auto.tone).toBe("positive");
  });

  it("완료되지 않고 끝난 비행은 경고로 남긴다", () => {
    const flight = deriveFieldStages(input({ execution: execution("ENDED_INCOMPLETE") }))[1];
    expect(flight.auto.tone).toBe("warning");
  });

  // 확정 결함 수정: 취소된 임무의 카드에서 auto 배지("비행하지 마세요")·[임무 시작]
  // 버튼(deriveFlightStart, "시작할 수 없습니다")은 날지 말라고 하는데 manual 만
  // "Pilot 2 앱에서 직접 시작할 수 있습니다"라고 초대하면 같은 카드 안에서 문장이
  // 서로 반대를 말한다.
  it("취소된 임무는 수동 경로도 시작을 권하지 않는다", () => {
    const flight = deriveFieldStages(input({ execution: execution("CANCELLED") }))[1];
    expect(flight.manual).not.toBeNull();
    expect(flight.manual).not.toContain("직접 시작할 수 있습니다");
    expect(flight.manual).toContain("취소된 임무");
  });
});

describe("[임무 시작] 버튼", () => {
  // `FlightStartControl.enabled` 는 타입 자체가 `false` 리터럴이라
  // `expect(control.enabled).toBe(false)` 는 컴파일 시점에 이미 강제되는 항진
  // 단언이다(field-stages.ts 의 그 타입 docstring 참조) — 여기서는 사유 문장만
  // 다룬다. 실제 화면이 이 값을 **읽는지**는 아래 "렌더된 버튼" 블록이 확인한다.
  it("사유 문장은 상태마다 비어 있지 않다", () => {
    for (const status of MISSION_EXECUTION_STATUSES) {
      expect(
        deriveFlightStart({ execution: execution(status) }).reason.length,
        `${status} 에서 사유 문장이 비었다`,
      ).toBeGreaterThan(0);
    }
    expect(deriveFlightStart({ execution: null }).reason.length).toBeGreaterThan(0);
  });

  it("취소된 임무에는 다른 사유를 말한다 — '아직 없다'와 '이건 취소됐다'는 다른 사실이다", () => {
    expect(deriveFlightStart({ execution: execution("CANCELLED") }).reason).toContain("취소된 임무");
    expect(deriveFlightStart({ execution: execution("ACTIVATED") }).reason).toContain("자동 시작 경로");
  });
});

describe("[임무 시작] 버튼 — 렌더된 화면 배선", () => {
  // 컴포넌트는 서버 컴포넌트라 노드 환경에서 렌더할 수 없다(vitest.config.ts —
  // 이 프로젝트는 jsdom 을 두지 않는다). 그래서 소스에서 배선 지점을 확인한다
  // (event-actions-token.test.ts 와 같은 관습).
  const PAGE_SOURCE = readFileSync(
    join(process.cwd(), "src/app/field/[missionId]/page.tsx"),
    "utf8",
  );

  it("버튼의 disabled 가 하드코딩이 아니라 deriveFlightStart 의 결과(control.enabled)를 읽는다", () => {
    expect(PAGE_SOURCE).toMatch(/disabled=\{!flightStart\.enabled\}/);
  });

  it("사유 문장이 실제로 화면에 나타난다", () => {
    expect(PAGE_SOURCE).toMatch(/\{flightStart\.reason\}/);
  });
});

describe("③ 사진 회수", () => {
  it("등록된 적 없는 임무를 0장 진행 중으로 보여주지 않는다", () => {
    const media = deriveFieldStages(input({ media: { kind: "not-registered" } }))[2];
    expect(media.auto.label).toBe("없음");
    expect(media.auto.tone).toBe("neutral");
  });

  it("봉인 전 장수를 그대로 보여준다", () => {
    const media = deriveFieldStages(
      input({ media: { kind: "registered", bundle: bundle({ mediaCount: 412 }) } }),
    )[2];
    expect(media.auto.label).toBe("봉인 전");
    expect(media.auto.detail).toContain("412장");
    expect(media.auto.tone).toBe("progress");
  });

  it("봉인되면 더 올릴 수 없다는 사실까지 말한다", () => {
    const media = deriveFieldStages(
      input({
        media: {
          kind: "registered",
          bundle: bundle({ status: "SEALED", mediaCount: 3000, sealedAt: "2026-08-16T02:00:00Z" }),
        },
      }),
    )[2];
    expect(media.auto.label).toBe("봉인됨");
    expect(media.auto.detail).toContain("더 올릴 수 없습니다");
    expect(media.auto.tone).toBe("positive");
  });

  // 확정 결함 수정: 조회 실패("error")와 "등록된 적 없음"("not-registered")을
  // 같은 "없음"으로 뭉개지 않는다 — 뭉개면 Core 가 잠깐 불안정한 순간에도 이미
  // 올린 사진이 "없다"고 나오고, 그 화면이 유도하는 행동은 불필요한 재업로드다.
  it("조회 실패를 '없음'으로 뭉개지 않는다", () => {
    const media = deriveFieldStages(input({ media: { kind: "error" } }))[2];
    expect(media.auto.label).toBe("조회 실패");
    expect(media.auto.tone).toBe("warning");
    expect(media.auto.label).not.toBe("없음");
  });

  it("조회 실패에서도 수동 경로 문구는 그대로 남는다 — 실패 감지로만 나타나는 안내를 만들지 않는다", () => {
    const media = deriveFieldStages(input({ media: { kind: "error" } }))[2];
    expect(media.manual).toContain("구분해 보고하지 않습니다");
  });

  it("장수가 자동/수동 합계라는 사실을 항상 밝힌다 — 이걸 안 밝히면 진행률로 읽힌다", () => {
    const variants: FieldMediaInput[] = [
      { kind: "not-registered" },
      { kind: "registered", bundle: bundle({ mediaCount: 10 }) },
      { kind: "registered", bundle: bundle({ status: "SEALED", mediaCount: 10 }) },
    ];
    for (const media of variants) {
      const stage = deriveFieldStages(input({ media }))[2];
      expect(stage.manual).toContain("구분해 보고하지 않습니다");
    }
  });
});

describe("④ 결과", () => {
  it("보고가 없으면 없다고만 말한다", () => {
    const result = deriveFieldStages(input({ coverage: { kind: "not-reported" } }))[3];
    expect(result.auto.tone).toBe("neutral");
    expect(result.auto.detail).toContain("아직 도착하지 않았");
  });

  it("조회 실패를 '보고 없음'으로 뭉개지 않는다", () => {
    const result = deriveFieldStages(input({ coverage: { kind: "error" } }))[3];
    expect(result.auto.label).toBe("조회 실패");
    expect(result.auto.tone).toBe("warning");
  });

  it("서버 판정을 그대로 옮긴다", () => {
    const result = deriveFieldStages(
      input({ coverage: { kind: "reported", completionState: "COMPLETED", recoveryRecommended: false } }),
    )[3];
    expect(result.auto.label).toBe("완료");
    expect(result.auto.tone).toBe("positive");
  });

  it("완료여도 재관측 권고가 붙으면 초록 하나로 끝내지 않는다", () => {
    const result = deriveFieldStages(
      input({ coverage: { kind: "reported", completionState: "COMPLETED", recoveryRecommended: true } }),
    )[3];
    expect(result.auto.tone).toBe("caution");
    expect(result.auto.detail).toContain("재관측");
  });

  it("결과 단계에는 수동 경로가 없다 — 현장에서 판정을 바꿀 수 없다", () => {
    expect(deriveFieldStages(input())[3].manual).toBeNull();
  });
});

// ── 목록 화면 ──────────────────────────────────────────────────────────────

function mission(missionId: string, issuedAt: string): MissionRecordResponse {
  return {
    missionId,
    siteId: "site-1",
    missionType: "BASELINE_MAPPING",
    artifactKind: "pair",
    kmzSha256: null,
    routePattern: "lawnmower",
    waypointCount: 10,
    plannedCoverageRatio: 0.9,
    issuedAt,
    issuedBy: "op-1",
    assignedDeviceId: null,
    coverageCompletionState: null,
    derivedFrom: null,
  };
}

describe("오늘 임무 묶기", () => {
  // 기준: 2026-08-16 09:00 KST = 2026-08-16T00:00:00Z
  const now = "2026-08-16T00:00:00Z";

  it("서울 달력 날짜로 오늘을 가른다 — 서버 시간대가 아니라", () => {
    // 2026-08-15T20:00Z 는 서울로 8월 16일 05:00 이다. UTC 로 나누면 '어제'가 된다.
    const groups = groupFieldMissions(
      [mission("m-late", "2026-08-15T20:00:00Z"), mission("m-old", "2026-08-14T02:00:00Z")],
      now,
    );
    expect(groups.today.map((m) => m.missionId)).toEqual(["m-late"]);
    expect(groups.earlier.map((m) => m.missionId)).toEqual(["m-old"]);
  });

  it("최신 발급이 먼저 온다", () => {
    const groups = groupFieldMissions(
      [mission("m-1", "2026-08-16T01:00:00Z"), mission("m-2", "2026-08-16T05:00:00Z")],
      now,
    );
    expect(groups.today.map((m) => m.missionId)).toEqual(["m-2", "m-1"]);
  });

  it("오늘 것이 없어도 빈 화면을 주지 않는다 — 전날 발급분으로 비행하는 날이 흔하다", () => {
    const groups = groupFieldMissions([mission("m-old", "2026-08-10T02:00:00Z")], now);
    expect(groups.today).toEqual([]);
    expect(groups.earlier.map((m) => m.missionId)).toEqual(["m-old"]);
  });

  it("잘라낸 건수를 숨기지 않는다 — 무엇이 안 보이는지 모르는 목록은 신뢰를 잃는다", () => {
    const many = Array.from({ length: 15 }, (_, i) =>
      mission(`m-${i}`, `2026-08-0${(i % 9) + 1}T02:00:00Z`),
    );
    const groups = groupFieldMissions(many, now, 12);
    expect(groups.earlier).toHaveLength(12);
    expect(groups.hiddenCount).toBe(3);
  });

  it("임무가 하나도 없으면 세 값 모두 비어 있다", () => {
    expect(groupFieldMissions([], now)).toEqual({ today: [], earlier: [], hiddenCount: 0 });
  });
});
