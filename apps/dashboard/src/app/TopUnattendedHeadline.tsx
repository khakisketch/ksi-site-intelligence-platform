/** 홈의 업무 인박스 진입점은 읽지 않은 플랫폼 업무만 표시한다. */
export function TopUnattendedHeadline({ pendingCount }: { pendingCount: number | null }) {
  if (pendingCount === null) return <>받은 업무 확인 불가</>;
  return pendingCount === 0 ? <>받은 업무</> : <>받은 업무 {pendingCount}건</>;
}
