import type { SiteProcessingJobSummary } from "@/lib/core-api/types";

/**
 * 현장 상세의 "조사 기록" 줄 — 그 현장에서 실제로 돌아간 **재구성 시점(epoch)** 목록.
 *
 * ── 무엇을 싣고 무엇을 싣지 않나 ─────────────────────────────────────────
 * 비교 후보만 고르는 `comparison-submit.selectableEpochs` 와 달리 여기는 **성공하지
 * 않은 것도 싣는다**. 이 줄은 고르는 자리가 아니라 이력이라서다: 지난주에 건 처리가
 * 실패해서 그 시점 결과가 없다는 사실이 화면에서 사라지면, 운영자는 "왜 그 날짜가
 * 없지"를 다른 화면에서 다시 찾아야 한다.
 *
 * 두 시점 비교의 제출 규칙(어느 쪽이 기준이 될 수 있는지, 무엇이 있어야 무엇을 잴 수
 * 있는지)은 `comparison-submit.ts` 가 소유한다 — 여기서 그 판정을 복제하지 않는다.
 */
export interface SiteEpoch {
  jobId: string;
  missionId: string;
  issuedAt: string;
  status: string;
  /** 이 시점이 만들어낸 산출물 종류(ortho·dsm·point_cloud …). 없으면 빈 배열. */
  artifactKinds: string[];
}

export function toSiteEpochs(jobs: readonly SiteProcessingJobSummary[]): SiteEpoch[] {
  return jobs
    .map((job) => ({
      jobId: job.jobId,
      missionId: job.missionId,
      issuedAt: job.issuedAt,
      status: job.status,
      artifactKinds: job.artifacts.map((artifact) => artifact.kind),
    }))
    // 서버가 최신순으로 준다는 계약에 기대지 않는다 — 시간축 줄에서 순서가 흔들리면
    // 그건 화면이 아니라 사실이 흔들려 보인다.
    .sort((a, b) => b.issuedAt.localeCompare(a.issuedAt));
}

/**
 * URL 의 `epoch` 값을 **실재하는 시점으로만** 받는다.
 *
 * 사용자가 손으로 고친 값이나 지워진 작업의 id 를 그대로 믿으면, 화면은 아무것도
 * 없는 시점의 요약을 그리려다 빈 화면을 낸다. 모르는 값이면 가장 최근 시점으로
 * 되돌린다(오류를 내지 않는다 — 이 파라미터는 보기 상태이지 명령이 아니다).
 */
export function resolveEpochId(
  epochs: readonly SiteEpoch[],
  raw: string | null | undefined,
): string | null {
  if (epochs.length === 0) return null;
  const hit = raw ? epochs.find((epoch) => epoch.jobId === raw) : undefined;
  return (hit ?? epochs[0]).jobId;
}

export function findEpoch(
  epochs: readonly SiteEpoch[],
  jobId: string | null,
): SiteEpoch | null {
  if (!jobId) return null;
  return epochs.find((epoch) => epoch.jobId === jobId) ?? null;
}

// 현장은 한국이고 서버는 어디서든 돈다 — 날짜 판정은 서울 기준으로 고정한다
// (lib/datetime.ts 와 같은 규율). 이 키는 표시용이 아니라 **같은 날인지** 비교용이다.
const SEOUL_DAY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Seoul",
});

/** 그 시점이 속한 서울 기준 날짜(YYYY-MM-DD). 파싱 불가면 원문을 키로 쓴다. */
export function epochDayKey(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? iso : SEOUL_DAY.format(when);
}

/**
 * **같은 날짜에 둘 이상 있는** 시점들의 날짜 — 그 날짜의 칩은 시각까지 보여야 한다.
 *
 * 실데이터로 처음 돌려본 날 바로 드러난 문제다(2026-08-18): 같은 날 두 번 처리한
 * 현장의 칩이 둘 다 "8. 18."로 찍혀 눈으로 구분되지 않았다. 상태 점 색이 다르긴
 * 하지만 그건 처리 상태이지 시점이 아니라, 둘 다 완료된 뒤에는 완전히 같아진다.
 *
 * 날짜가 겹치지 않는 흔한 경우에는 시각을 붙이지 않는다 — 모든 칩에 시각을 달면
 * 줄이 길어져 정작 며칠 간격인지가 안 읽힌다.
 */
export function ambiguousEpochDays(epochs: readonly SiteEpoch[]): Set<string> {
  const counts = new Map<string, number>();
  for (const epoch of epochs) {
    const key = epochDayKey(epoch.issuedAt);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return new Set([...counts].filter(([, n]) => n > 1).map(([key]) => key));
}

// ── 탭 ────────────────────────────────────────────────────────────────────
//
// 현장 상세는 예전에 카드 여덟 장을 세로로 쌓아, 각 카드가 "이런 기능이 있습니다"를
// 설명하고 링크 하나를 주는 안내판이었다. 탭은 그 안내를 **일 단위**로 접는다:
// 지금 무엇을 보려는지 고르면 그 아래는 그 일에 필요한 것만 남는다.

// 메뉴는 "무엇을 하러 오는가"로 나눈다: 작업공간(workspace)·자료(materials)·
// 결과(results)를 머리에서 바로 보인다. 관측 작업 기록(work-orders) 키와
// 현장 설정(manage) 키는 옛 URL(?section=...) 호환을 위해 남기되,
// 최상위 메뉴가 아니라 각각 자료 안의 하위 길과 머리 설정 메뉴로 둔다.
// 외부 비교 기록 같은 별도 목록은 결과 안의 하위 보기로 두고,
// KSI 계산 결과와 출처를 섞지 않는다.
export const SITE_TABS = [
  { key: "workspace", label: "작업공간" },
  { key: "materials", label: "자료" },
  { key: "results", label: "결과" },
  { key: "work-orders", label: "관측 작업 기록" },
  { key: "manage", label: "설정" },
] as const;

export type SiteTabKey = (typeof SITE_TABS)[number]["key"];

export function normalizeSiteTab(raw: string | null | undefined): SiteTabKey {
  const hit = SITE_TABS.find((tab) => tab.key === raw);
  if (hit) return hit.key;
  // 이전 URL·다른 화면의 옛 키는 가장 가까운 현재 영역으로만 옮긴다 — 원문 키를
  // 화면에 다시 노출하지 않는다. 기본 진입은 작업공간(workspace)이다.
  if (raw === "overview" || raw === "observations") return "workspace";
  if (raw === "spatial-assets" || raw === "data" || raw === "volume" || raw === "design") return "materials";
  if (raw === "work" || raw === "records") return "work-orders";
  if (raw === "analysis" || raw === "external-results" || raw === "reports" || raw === "review-items") return "results";
  return "workspace";
}
