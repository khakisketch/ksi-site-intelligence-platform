/** Read-only guidance; it never inspects, changes or transfers stored records. */
export function SiteRegistrationRecoveryGuidance({ confirmed = false }: { confirmed?: boolean }) {
  return (
    <div className="flex flex-col items-start gap-2 text-[12px] break-keep">
      <p>이 탭을 닫거나 새로고침하지 말고 원래 계정을 확인하세요. 저장소를 지우거나 기록을 추측해 옮기지 마세요. 남은 백업은 자동으로 복구하거나 삭제하지 않습니다.</p>
      <p>탭 저장 내용은 탭을 닫으면 사라질 수 있고 같은 출처에서 평문으로 접근할 수 있습니다. 진행 중인 포인터 편집은 복원되지 않습니다.</p>
      {!confirmed && <p>등록 결과가 확인되지 않았다면 현장 목록을 살펴봐도 요청 결과가 확정되는 것은 아닙니다. 같은 요청을 새로 보내기 전에 원래 계정에서 확인하세요.</p>}
      <p>별도 탭의 저장소가 분리되는 브라우저에서만 새로 시작하세요. 새 탭을 열지 못하거나 저장소를 확인할 수 없으면 진행하지 마세요. 이 탭은 그대로 유지하세요.</p>
      <a href="/sites" target="_blank" rel="noopener noreferrer" className="tap-target font-semibold underline underline-offset-2">별도 탭에서 현장 목록 확인하기</a>
      <a href="/sites/new" target="_blank" rel="noopener noreferrer" className="tap-target font-semibold underline underline-offset-2">별도 탭에서 새로 시작하기</a>
    </div>
  );
}
