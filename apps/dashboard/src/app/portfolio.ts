import type { SiteStatus } from "@/lib/core-api/types";
import type { OperatorNextAction } from "@/lib/operator-next-action";

/**
 * 홈 포트폴리오 표의 한 행 — **서버에서 이미 확정된 값만** 담는다.
 *
 * 시안의 "다음 정기 조사"·"계획 대비 지연"·"주당 변화 추세" 세 열은 여기 없다.
 * 이 시스템에는 조사 주기도 계획 일정도 시계열 집계도 없다 — 화면이 그 세 값을
 * 그리려면 지어내는 수밖에 없고, 그건 현황판이 해서는 안 되는 유일한 일이다
 * (INV-040). 대신 실제로 아는 것만 센다: 마지막 임무 발급 시각, 미조치 이벤트
 * 수, 등록일.
 */
export interface PortfolioRow {
  siteId: string;
  name: string;
  status: SiteStatus;
  registeredAt: string;
  /** 그 현장에 마지막으로 **발급된** 임무 시각. 발급 이력이 없으면 null. */
  lastMissionAt: string | null;
  /**
   * 미조치 이벤트 수. `null` 은 0 이 아니라 **세지 못했다**는 뜻이다(권한 없음
   * 또는 조회 실패) — 표는 이 둘을 절대 같은 칸으로 그리지 않는다.
   */
  unattendedCount: number | null;
  /** 기준 지도가 없어 순찰을 시작할 수 없는 상태(UNMAPPED·REMAP_REQUIRED). */
  blocked: boolean;
  /** 현재 AOI·상태·권한으로 결정된 바로가기. 없으면 쓰기 행동을 만들지 않는다. */
  primaryAction: OperatorNextAction | null;
}

export const PORTFOLIO_SORTS = [
  { key: "attention", label: "확인 필요한 순" },
  { key: "recent", label: "최근 임무 순" },
  { key: "registered", label: "최근 등록 순" },
  { key: "name", label: "현장명 순" },
] as const;

export type PortfolioSort = (typeof PORTFOLIO_SORTS)[number]["key"];

export const DEFAULT_PORTFOLIO_SORT: PortfolioSort = "attention";

/**
 * URL 의 `sort` 는 사용자가 직접 편집할 수 있는 신뢰 경계 밖 입력이다 — 아는 값만
 * 받고 나머지는 조용히 기본값으로 되돌린다(오류 화면을 내지 않는다,
 * `surveyEntryPreset.resolveInitialMissionType` 과 같은 규약).
 */
export function normalizePortfolioSort(raw: string | null | undefined): PortfolioSort {
  const hit = PORTFOLIO_SORTS.find((option) => option.key === raw);
  return hit ? hit.key : DEFAULT_PORTFOLIO_SORT;
}

/** 검색어 정규화 — 대소문자와 좌우 공백을 무시한다(팔레트 `normalizeQuery` 와 같은 규칙). */
export function normalizePortfolioQuery(raw: string | null | undefined): string {
  return (raw ?? "").trim().toLowerCase();
}

/**
 * 이름 또는 현장 ID 로 거른다.
 *
 * ID 를 포함하는 이유는 팔레트와 같다 — 현장명을 정확히 기억 못 해도 도달할 수
 * 있어야 한다. 상태 라벨로는 거르지 않는다: 표에 상태 배지가 이미 보이고, 라벨
 * 문자열을 검색 대상에 넣으면 "순찰"이 상태와 이름 양쪽에 걸려 결과가 왜 나왔는지
 * 설명되지 않는다.
 */
export function filterPortfolio(rows: readonly PortfolioRow[], query: string): PortfolioRow[] {
  const q = normalizePortfolioQuery(query);
  if (!q) return [...rows];
  return rows.filter(
    (row) => row.name.toLowerCase().includes(q) || row.siteId.toLowerCase().includes(q),
  );
}

function byNameKo(a: PortfolioRow, b: PortfolioRow): number {
  return a.name.localeCompare(b.name, "ko");
}

/** ISO 시각 내림차순 — 값이 없는 행은 항상 뒤로 보낸다("없음"이 "가장 오래됨"은 아니다). */
function byIsoDesc(a: string | null, b: string | null): number {
  if (a === b) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return new Date(b).getTime() - new Date(a).getTime();
}

/**
 * 정렬. 어떤 기준이든 **동점은 현장명 순**으로 풀어 순서를 결정론적으로 만든다 —
 * 새로고침마다 행이 뒤바뀌면 운영자는 표를 다시 읽는다.
 *
 * `attention`(기본)의 순서는 "순찰을 시작조차 못 하는 현장 → 미조치가 많은 현장"
 * 이다. 미조치 수를 못 구한 행(`null`)은 0 과 같은 자리에 둔다 — 모르는 값을
 * 위로 올려 급한 것처럼 보이게 하지도, 아래로 감추지도 않는다. 그 칸은 "—" 로
 * 그려져 세지 못했음이 표에 그대로 보인다.
 */
export function sortPortfolio(rows: readonly PortfolioRow[], sort: PortfolioSort): PortfolioRow[] {
  const copy = [...rows];
  switch (sort) {
    case "attention":
      return copy.sort((a, b) => {
        if (a.blocked !== b.blocked) return a.blocked ? -1 : 1;
        const diff = (b.unattendedCount ?? 0) - (a.unattendedCount ?? 0);
        return diff !== 0 ? diff : byNameKo(a, b);
      });
    case "recent":
      return copy.sort((a, b) => {
        const diff = byIsoDesc(a.lastMissionAt, b.lastMissionAt);
        return diff !== 0 ? diff : byNameKo(a, b);
      });
    case "registered":
      return copy.sort((a, b) => {
        const diff = byIsoDesc(a.registeredAt, b.registeredAt);
        return diff !== 0 ? diff : byNameKo(a, b);
      });
    case "name":
      return copy.sort(byNameKo);
  }
}

/** 검색·정렬을 한 번에 — 화면은 이 함수 하나만 부른다. */
export function derivePortfolio(
  rows: readonly PortfolioRow[],
  query: string,
  sort: PortfolioSort,
): PortfolioRow[] {
  return sortPortfolio(filterPortfolio(rows, query), sort);
}
