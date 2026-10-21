/**
 * R1–R5 기준 탐색 + M1–M5 게이지(측정 전용).
 *
 * 첫지불 설계 §5의 수락 형식 그대로다. 카운터·마크·게이지만 두며,
 * 제품 의미를 바꾸지 않는다 — 요청/응답 본문·grant 검사·영수증
 * 게이트·스케줄러 순서·레인 동시성을 건드리지 않고, 사용자 표시
 * 문구를 만들지 않으며, 동작을 바꾸지 않는다. 실제 제품에서는
 * 스케줄러 리스너·보관 serve 호출·성능 마크에 손으로 묶어 수집한다.
 *
 * 수치 통과 기준은 전부 벤치마크 목표(TBD)로 열어 둔다. 아래
 * `MEASURED_BASIS`는 측정 증거에서 온 보고용 기준값이며 기준이 아니다:
 * 차가움 첫 픽셀 ≈5.8 s·차가움 안정 ≈23 s·따뜻함 재방문 ≈0.7 s·
 * T1 ≤100 ms는 브라우저 증거가 필요한 목표다.
 *
 * Invariants: INV-040(합성 채움 금지 — 게이지가 표시를 바꾸지 않음)/
 * INV-060·061(권한·이그레스 — 게이지가 권리 사실을 만들지 않음).
 */

/** 기준 탐색 순서 버전 — 결과와 함께 기록한다. */
export const REFERENCE_RUN_SEQUENCE_VERSION = "R1-R5-v1";

export type ReferencePhase = "R1" | "R2" | "R3" | "R4" | "R5";

export const REFERENCE_PHASES: readonly ReferencePhase[] = [
  "R1",
  "R2",
  "R3",
  "R4",
  "R5",
];

/** 측정 증거에서 온 보고용 기준값(통과 기준이 아님). */
export const MEASURED_BASIS = {
  /** 신선 전체 커버 첫 COMPLETED 5.62 s + 재수집 ≈0.14 s (MEASURED). */
  coldFirstPixelMs: 5800,
  /** 신선 전체 커버 벽시계 22.9 s (MEASURED, idle lane). */
  coldStabiliseMs: 23000,
  /** 준비済 커버 재수집+검증+디코드 0.691 s (MEASURED). */
  warmRevisitMs: 700,
  /** T1 경로 목표 — 벤치마크 목표이며 브라우저 증거가 필요하다(INFERRED). */
  t1TargetMs: 100,
  source: "docs/audit/SPATIAL_DISPLAY_CACHE_MEASUREMENT_EVIDENCE_2026-10-21.md",
} as const;

/**
 * 수치 통과 기준 — 전부 벤치마크가 정하기 전까지 열린 목표다.
 * 구현은 측정·보고만 하며, 어떤 숫자도 여기서 통과로 단정하지 않는다.
 */
export const REFERENCE_PASS_THRESHOLDS = {
  status: "TBD_BY_BENCHMARK",
  m1: "R2 무신규 PREPARE + 벤치마크율(TBD)",
  m2Warm: "벤치마크 상한(TBD) — 측정 근거: 따뜻함 ≈0.7 s, T1 목표 ≤100 ms",
  m2Cold: "보고 전용 — 측정 근거 ≈5.8 s",
  m3Cold: "측정 근거 ≤25 s (22.9 s + 지터 여유)",
  m3Warm: "벤치마크 상한(TBD)",
  m4: "FAILED-due-to-429 = 0; 스크립트 탐색은 2슬롯 규율로 429 0건",
  m5: "T1은 MOSAIC_T1_MAX_SLOTS 상한 안에서 방출(충돌 아님); T2 상한 TBD",
} as const;

export interface ReferenceFixtureIdentity {
  sourceWidth: number;
  sourceHeight: number;
  crsIdentifier: string;
  tileSize: number;
  viewportSequenceVersion: string;
  laneConditions: string;
}

export type ReferenceHitTier = "T1" | "T2";

/** 한 페이즈의 관측 요약 — 카운터·마크·게이지 값만 둔다. */
export interface ReferencePhaseSummary {
  phase: ReferencePhase;
  requested: number;
  t1Hits: number;
  t2Hits: number;
  misses: number;
  preparesIssued: number;
  r429: number;
  r429Recovered: number;
  r429Failed: number;
  /** viewport-commit → 첫 검증 paint (ms). 미관측이면 null이다. */
  firstPixelMs: number | null;
  /** viewport-commit → 커버 집합 해소 (ms). 미관측이면 null이다. */
  stabiliseMs: number | null;
  /** T1 상주 바이트 표본(최대). */
  residencyBytes: number;
}

function emptyPhase(phase: ReferencePhase): ReferencePhaseSummary {
  return {
    phase,
    requested: 0,
    t1Hits: 0,
    t2Hits: 0,
    misses: 0,
    preparesIssued: 0,
    r429: 0,
    r429Recovered: 0,
    r429Failed: 0,
    firstPixelMs: null,
    stabiliseMs: null,
    residencyBytes: 0,
  };
}

/**
 * 기준 탐색 게이지 수집기. 제품 상태가 아니라 측정 기록이며,
 * 같은 페이즈에 반복 기록해도 동작을 바꾸지 않는다.
 */
export class DisplayReferenceGauges {
  private readonly phases = new Map<ReferencePhase, ReferencePhaseSummary>();
  private readonly commitMarks = new Map<ReferencePhase, number>();

  private at(phase: ReferencePhase): ReferencePhaseSummary {
    const existing = this.phases.get(phase);
    if (existing) return existing;
    const created = emptyPhase(phase);
    this.phases.set(phase, created);
    return created;
  }

  recordRequest(phase: ReferencePhase, count = 1): void {
    this.at(phase).requested += count;
  }

  recordHit(phase: ReferencePhase, tier: ReferenceHitTier, count = 1): void {
    const summary = this.at(phase);
    if (tier === "T1") summary.t1Hits += count;
    else summary.t2Hits += count;
  }

  recordMiss(phase: ReferencePhase, count = 1): void {
    this.at(phase).misses += count;
  }

  recordPrepare(phase: ReferencePhase, count = 1): void {
    this.at(phase).preparesIssued += count;
  }

  record429(phase: ReferencePhase, outcome: "recovered" | "failed"): void {
    const summary = this.at(phase);
    summary.r429 += 1;
    if (outcome === "recovered") summary.r429Recovered += 1;
    else summary.r429Failed += 1;
  }

  markViewportCommit(phase: ReferencePhase, nowMs: number): void {
    this.commitMarks.set(phase, nowMs);
  }

  markFirstPaintVerified(phase: ReferencePhase, nowMs: number): void {
    const summary = this.at(phase);
    const commit = this.commitMarks.get(phase);
    if (commit === undefined || summary.firstPixelMs !== null) return;
    summary.firstPixelMs = nowMs - commit;
  }

  markStabilised(phase: ReferencePhase, nowMs: number): void {
    const summary = this.at(phase);
    const commit = this.commitMarks.get(phase);
    if (commit === undefined || summary.stabiliseMs !== null) return;
    summary.stabiliseMs = nowMs - commit;
  }

  sampleResidency(phase: ReferencePhase, bytes: number): void {
    const summary = this.at(phase);
    if (bytes > summary.residencyBytes) summary.residencyBytes = bytes;
  }

  snapshot(): ReferencePhaseSummary[] {
    return REFERENCE_PHASES.filter((phase) => this.phases.has(phase)).map(
      (phase) => ({ ...(this.phases.get(phase) as ReferencePhaseSummary) }),
    );
  }

  reset(): void {
    this.phases.clear();
    this.commitMarks.clear();
  }
}

export interface DerivedM1M5 {
  /** M1 적중률 — R1–R4 합산. R5(권리 뒤집기)는 별도 불변식으로 센다. */
  m1: { overall: number; t1: number; t2: number; requested: number; hits: number };
  /** M2 첫 유효 픽셀 — R1(차가움, 보고 전용)과 R2(따뜻함). */
  m2: { coldMs: number | null; warmMs: number | null };
  /** M3 안정화 — R1(차가움)과 R2/R3(따뜻함) 중 관측된 값. */
  m3: { coldMs: number | null; warmMs: number[] };
  /** M4 429율 — R1–R4 합산. */
  m4: { rate429: number; issues: number; failed429: number };
  /** M5 메모리 — 관측된 최대 T1 상주 바이트. */
  m5: { peakResidencyBytes: number };
  /** R5 불변식 — 어느 tier에서도 0건이어야 한다. */
  r5ServedFromTier: number;
}

/** 합성 타임라인 고정값(TEST FIXTURE)에서 M1–M5를 유도한다(순수 함수). */
export function deriveM1M5(phases: readonly ReferencePhaseSummary[]): DerivedM1M5 {
  const scored = phases.filter((item) => item.phase !== "R5");
  const requested = scored.reduce((sum, item) => sum + item.requested, 0);
  const t1 = scored.reduce((sum, item) => sum + item.t1Hits, 0);
  const t2 = scored.reduce((sum, item) => sum + item.t2Hits, 0);
  const hits = t1 + t2;
  const issues = scored.reduce((sum, item) => sum + item.preparesIssued, 0);
  const r429 = scored.reduce((sum, item) => sum + item.r429, 0);
  const r429Failed = scored.reduce((sum, item) => sum + item.r429Failed, 0);
  const r1 = phases.find((item) => item.phase === "R1");
  const r2 = phases.find((item) => item.phase === "R2");
  const warm = phases.filter(
    (item) => (item.phase === "R2" || item.phase === "R3") && item.stabiliseMs !== null,
  );
  const r5 = phases.find((item) => item.phase === "R5");
  return {
    m1: {
      overall: requested === 0 ? 0 : hits / requested,
      t1: requested === 0 ? 0 : t1 / requested,
      t2: requested === 0 ? 0 : t2 / requested,
      requested,
      hits,
    },
    m2: { coldMs: r1?.firstPixelMs ?? null, warmMs: r2?.firstPixelMs ?? null },
    m3: {
      coldMs: r1?.stabiliseMs ?? null,
      warmMs: warm.map((item) => item.stabiliseMs as number),
    },
    m4: {
      rate429: issues === 0 ? 0 : r429 / issues,
      issues,
      failed429: r429Failed,
    },
    m5: {
      peakResidencyBytes: phases.reduce(
        (peak, item) => Math.max(peak, item.residencyBytes),
        0,
      ),
    },
    r5ServedFromTier: (r5?.t1Hits ?? 0) + (r5?.t2Hits ?? 0),
  };
}

/**
 * 정직한 차가움/따뜻함 보고 — 측정값만 말하며, "즉시"·"최신" 같은
 * fabricated 표현을 쓰지 않는다. 수치 기준은 벤치마크 목표(TBD)로
 * 열어 둔다.
 */
export function honestColdWarmCopy(): string {
  return (
    `첫 유효 픽셀 · 측정값 기준 차가움 약 ${(MEASURED_BASIS.coldFirstPixelMs / 1000).toFixed(1)}초 / ` +
    `다시 보기 약 ${(MEASURED_BASIS.warmRevisitMs / 1000).toFixed(1)}초 · ` +
    `T1 ${MEASURED_BASIS.t1TargetMs}ms 이하는 벤치마크 목표(미확정) · ` +
    `즉시·최신 표현 없음 · 기준 ${REFERENCE_RUN_SEQUENCE_VERSION}`
  );
}
