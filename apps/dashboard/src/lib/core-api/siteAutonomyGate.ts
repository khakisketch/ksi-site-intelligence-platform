// 정본: packages/domain/src/ksi_domain/enums.py requires_autonomy_approval
// (ADR-KSI-015 D2). 서버가 최종 권위이고(403 은 여전히 서버가 검사한다), 이
// 파일은 현장 상세 전이 UI(SiteTransitionActions.tsx)가 관리자 전용 대상을
// 미리 숨기기 위한 미러다 — 서버 403 을 마지막에 만나게 하지 않는다.
//
// **간선(cur, nxt) 쌍 기준 판정이다 — 목적지 상태만으로 가르지 않는다.**
// PATROL_READY 로 들어오는 정적 간선이 둘이다(PROVISIONAL_AUTONOMY→ 최초 정식
// 승인·PATROL_ACTIVE→ 순찰 후 정상 복귀) — 목적지 상태 하나만 보면 순찰 복귀까지
// 관리자 전용으로 잘못 막는다(이 파일에서 가장 틀리기 쉬운 지점, ADR 본문 "구현
// 시 정확히 지킬 것" 항목).
//
// 대상 전이 집합은 도메인 개념이라 Python 쪽
// ``_AUTONOMY_APPROVAL_GATED_TRANSITIONS`` 가 SSOT다. 표가 갈리면
// tests/contract/test_site_autonomy_gate_dashboard_sync.py 가 잡는다
// (ADR-KSI-014 D4 이중유지 리스크와 같은 관습, missionSiteGate.ts 와 동형).
import type { SiteStatus } from "./types";

const AUTONOMY_APPROVAL_GATED_TRANSITIONS: ReadonlySet<string> = new Set([
  "MODEL_VALIDATION->PROVISIONAL_AUTONOMY", // 자율 시작 승인
  "PROVISIONAL_AUTONOMY->PATROL_READY", // 정식 순찰 승인
]);

/**
 * ``cur → nxt`` 전이가 자율운영 승인(``SITES_AUTONOMY_APPROVE``, 관리자 전용)을
 * 요구하는지. Python SSOT 와 동형인 세 갈래 판정:
 *
 * - ``nxt`` 가 ``SUSPENDED``: 모든 상태에서의 운영중단 진입은 출발 상태와 무관하게
 *   게이트된다.
 * - ``cur`` 가 ``SUSPENDED``: 운영중단 복귀(resume)는 목적지와 무관하게 게이트된다.
 * - 그 외: 정적 표(``AUTONOMY_APPROVAL_GATED_TRANSITIONS``)를 따른다 — 예를 들어
 *   ``PATROL_ACTIVE → PATROL_READY``(순찰 복귀)는 이 표에 없으므로 게이트되지 않는다.
 */
export function requiresAutonomyApproval(cur: SiteStatus, nxt: SiteStatus): boolean {
  if (nxt === "SUSPENDED" || cur === "SUSPENDED") return true;
  return AUTONOMY_APPROVAL_GATED_TRANSITIONS.has(`${cur}->${nxt}`);
}
