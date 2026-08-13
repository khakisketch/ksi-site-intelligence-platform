import type { DesignSurface, SiteProcessingJobSummary } from "@/lib/core-api/types";

/**
 * 설계 기준면 화면의 **순수 판정** — 렌더링과 분리해 테스트 가능하게 둔다
 * (`comparison-submit.ts` 와 같은 자리·같은 규율).
 *
 * 서버 판정을 복제하지 않는다. 최종 가부는 Core 가 정하고, 여기 있는 것은
 * 제출 전 안내와 표시 규칙뿐이다.
 */

/**
 * presigned PUT 에 실을 Content-Type — **서명에 포함된 값이라 바꿀 수 없다**.
 *
 * Core 가 `DESIGN_SURFACE_CONTENT_TYPE = "application/octet-stream"` 으로
 * 서명하므로(`evidence_s3.presigned_put` 이 ContentType 을 서명에 넣는다),
 * 브라우저가 파일의 MIME(`.tif` → `image/tiff`)을 그대로 보내면 서명이 깨져
 * 403 이 된다. 사진 업로드(`SourceUploadPanel`)가 `file.type` 을 쓰는 것과
 * 다른 이유가 이것이다 — 그쪽은 등록 시 신고한 contentType 으로 서명된다.
 */
export const DESIGN_SURFACE_UPLOAD_CONTENT_TYPE = "application/octet-stream";

/** 판정이 끝나 더 기다릴 것이 없는 상태 — 이 값이면 폴링을 멈춘다. */
const TERMINAL_DESIGN_SURFACE_STATUSES = new Set<string>(["VERIFIED", "REJECTED"]);

export function isTerminalDesignSurfaceStatus(status: string): boolean {
  return TERMINAL_DESIGN_SURFACE_STATUSES.has(status);
}

/**
 * 비교 입력이 될 수 있는 설계면만 — `VERIFIED` 하나뿐이다.
 *
 * 계약(`DesignSurface.is_usable_for_conformance`)이 같은 판정을 서버에서
 * 하고 있고, 여기서 느슨해지면 **아무도 읽어보지 않은 파일**이 선택지에 뜬다.
 */
export function conformanceReadySurfaces(
  surfaces: readonly DesignSurface[],
): DesignSurface[] {
  return surfaces.filter((surface) => surface.status === "VERIFIED");
}

/** 재구성이 끝나 설계 대비 비교의 "현재 지형"이 될 수 있는 결과만(높이자료 필수). */
export function designComparableJobs(
  jobs: readonly SiteProcessingJobSummary[],
  missionId: string,
): SiteProcessingJobSummary[] {
  return jobs
    .filter(
      (job) =>
        job.status === "SUCCEEDED" &&
        job.missionId === missionId &&
        job.artifacts.some((artifact) => artifact.kind === "dsm"),
    )
    .sort((a, b) => b.issuedAt.localeCompare(a.issuedAt));
}

/** 선언 vs 관측 대조표의 한 행 — 값이 갈렸는지는 서버가 이미 판정했다. */
export interface DeclaredObservedRow {
  label: string;
  /** 사용자가 적어 낸 값. */
  declared: string;
  /** 서버가 파일을 열어 잰 값. 아직 아무도 재지 않았으면 null. */
  observed: string | null;
}

const NOT_MEASURED = null;

/**
 * 선언 vs 관측 대조표를 만든다 — **선언에만 있는 항목도 행으로 남긴다.**
 *
 * GeoTIFF 는 수직기준을 신뢰성 있게 담지 않아 관측할 수 없다. 그 행을 표에서
 * 빼 버리면 화면이 "이 값도 확인됐다"고 말하는 것과 같아진다 — 대신 행을 두고
 * 관측 칸을 "파일에서 확인할 수 없음"으로 채운다.
 */
export function declaredObservedRows(surface: DesignSurface): DeclaredObservedRow[] {
  const observed = surface.observed;
  return [
    {
      label: "파일 해시(sha256)",
      declared: surface.declared.sha256,
      observed: observed ? observed.sha256 : NOT_MEASURED,
    },
    {
      label: "좌표계",
      declared: surface.declared.crs,
      observed: observed ? observed.crs : NOT_MEASURED,
    },
    {
      label: "평면 단위",
      declared: "미터",
      observed: observed ? "미터(좌표계에서 확인)" : NOT_MEASURED,
    },
    {
      label: "격자 크기",
      declared: "—",
      observed: observed ? `${observed.width} × ${observed.height} 화소` : NOT_MEASURED,
    },
    {
      label: "화소 크기",
      declared: "—",
      observed: observed
        ? `${observed.pixelSizeXM.toFixed(3)} × ${observed.pixelSizeYM.toFixed(3)} m`
        : NOT_MEASURED,
    },
    {
      label: "밴드 수",
      declared: "1 (높이 자료)",
      observed: observed ? `${observed.bandCount}` : NOT_MEASURED,
    },
    {
      label: "유효 높이 셀",
      declared: "—",
      observed: observed ? `${observed.finiteCellCount.toLocaleString("ko-KR")}개` : NOT_MEASURED,
    },
    {
      label: "파일 안의 높이 기준(수직 CRS)",
      declared: "—",
      observed: observed
        ? observed.verticalCrsEpsg === null
          ? "파일에 없음(정상 — 대부분의 높이자료가 그렇습니다)"
          : `EPSG:${observed.verticalCrsEpsg}`
        : NOT_MEASURED,
    },
  ];
}

/**
 * 차분 래스터 한 셀이 화면에서 무엇으로 그려지는가 — **3상태 고정**.
 *
 * | 셀 | 뜻 |
 * |---|---|
 * | `unknown` | 측정 불가(NaN). **0 으로 그리지 않는다** — 0 은 "설계대로 됐다"는 뜻이 있는 값이라, 모르는 곳을 0 으로 칠하면 지도가 거짓말한다. |
 * | `below-threshold` | 문턱 미만 — 실제 값은 있지만 **집계에서 제외됐다**. 그 사실이 색으로 드러나야 표의 숫자와 지도가 같은 말을 한다. |
 * | `fill` / `cut` | 집계에 들어간 값. 양수 = 설계가 높다 = 쌓아야 함, 음수 = 깎아야 함. |
 *
 * `thresholdM` 은 **리포트가 싣고 온 값**을 받는다 — 화면이 자기 상수를 갖지
 * 않는다(`comparison_policy.py` 가 세운 원칙 그대로).
 */
export type DiffCellClass = "unknown" | "below-threshold" | "fill" | "cut";

export function classifyDiffCell(value: number | null, thresholdM: number): DiffCellClass {
  if (value === null || !Number.isFinite(value)) return "unknown";
  if (Math.abs(value) < thresholdM) return "below-threshold";
  return value > 0 ? "fill" : "cut";
}

/** 3상태 팔레트 — 지도와 범례가 **같은 표**에서 색을 읽는다. */
export const DIFF_CELL_COLOR: Record<DiffCellClass, string> = {
  // 모름은 회색이다. 발산형 팔레트의 어느 끝과도 헷갈리면 안 된다.
  unknown: "#9aa0a6",
  // 중립색 — 집계에 안 들어갔다는 뜻이지 "차이가 0"이라는 뜻이 아니다.
  "below-threshold": "#e8e6e1",
  // 쌓아야 함(설계가 높다) — 파랑 계열.
  fill: "#2a6fb0",
  // 깎아야 함(현재가 높다) — 주황 계열. 색맹 대비로 파랑↔주황 축을 쓴다.
  cut: "#c1651a",
};

export const DIFF_CELL_LABEL: Record<DiffCellClass, string> = {
  unknown: "측정 불가(모름)",
  "below-threshold": "문턱 미만 — 집계 제외",
  fill: "성토 필요(쌓아야 함)",
  cut: "절토 필요(깎아야 함)",
};

/**
 * 발산형 팔레트의 세기 — |값| 이 `maxAbsM` 에 가까울수록 진하다.
 *
 * 0..1 로 정규화만 하고 색은 위 표가 정한다. `maxAbsM` 이 0 이하이면(전 셀이
 * 문턱 미만인 경우) 세기를 나눌 근거가 없으므로 최댓값으로 고정한다 — 흐리게
 * 그려서 "값이 작다"고 오해하게 만들지 않는다.
 */
export function diffIntensity(value: number, maxAbsM: number): number {
  if (!(maxAbsM > 0)) return 1;
  return Math.min(1, Math.abs(value) / maxAbsM);
}

/**
 * 아직 판정을 기다리는 설계면이 하나라도 있는가 — 있으면 그 현장 id, 없으면 null.
 *
 * `SEALED` 만 본다. `REGISTERED` 는 파일이 아직 안 올라온 상태라 서버가 아무것도
 * 하지 않으며, 그것 때문에 폴링을 계속 돌리면 영원히 멈추지 않는 타이머가 된다.
 */
export function pendingVerification(surfaces: readonly DesignSurface[]): boolean {
  return surfaces.some((surface) => surface.status === "SEALED");
}
