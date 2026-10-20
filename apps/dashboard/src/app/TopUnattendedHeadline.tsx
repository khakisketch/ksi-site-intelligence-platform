/** 홈의 업무 인박스 진입점은 읽지 않은 플랫폼 업무만 표시한다.
 * `받은 업무함`은 할당·공유 결과의 함이며, 현장 기록 단위인 `관측 작업`과 구분한다. */
export function TopUnattendedHeadline({ pendingCount }: { pendingCount: number | null }) {
  if (pendingCount === null) return <>받은 업무함 확인 불가</>;
  return pendingCount === 0 ? <>받은 업무함</> : <>받은 업무함 {pendingCount}건</>;
}
