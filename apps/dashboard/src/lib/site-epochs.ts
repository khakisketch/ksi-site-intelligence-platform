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

// ── 탭 ────────────────────────────────────────────────────────────────────
//
// 현장 상세는 예전에 카드 여덟 장을 세로로 쌓아, 각 카드가 "이런 기능이 있습니다"를
// 설명하고 링크 하나를 주는 안내판이었다. 탭은 그 안내를 **일 단위**로 접는다:
// 지금 무엇을 보려는지 고르면 그 아래는 그 일에 필요한 것만 남는다.

export const SITE_TABS = [
  { key: "overview", label: "개요" },
  { key: "volume", label: "변화 · 물량" },
  { key: "design", label: "설계 · 구역" },
  { key: "records", label: "기록 · 관리" },
] as const;

export type SiteTabKey = (typeof SITE_TABS)[number]["key"];

export function normalizeSiteTab(raw: string | null | undefined): SiteTabKey {
  const hit = SITE_TABS.find((tab) => tab.key === raw);
  return hit ? hit.key : "overview";
}
