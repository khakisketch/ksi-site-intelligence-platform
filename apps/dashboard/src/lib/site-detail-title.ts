/**
 * 현장 상세 문서 제목은 대상 이름을 먼저 둔다. 앱 셸의 위치 제목("현장 상세")과
 * 브라우저 탭의 식별 목적이 다르므로, 탭에서는 여러 현장을 오갈 때 구분 가능한
 * 실제 현장명을 유지한다.
 */
export function siteDetailDocumentTitle(siteName: string): string {
  return `${siteName} · 현장 · KSI`;
}
