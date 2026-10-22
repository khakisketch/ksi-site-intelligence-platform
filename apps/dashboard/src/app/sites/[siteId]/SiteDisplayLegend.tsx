/** State key, not a claim about any particular undrawn pixel or analysis decision. */
export function SiteDisplayLegend() {
  return <details className="border-t border-line px-3 py-2 text-[12px] leading-5 text-ink-2">
    <summary className="tap-target cursor-pointer font-semibold">지도 범례 · 표시와 분석의 차이</summary>
    <p className="mt-2">지도에는 확인된 유효 픽셀만 그립니다. 빈 영역만으로 원본 유무나 분석 가능 여부를 판단하지 않습니다.</p>
    <dl className="mt-2 grid gap-3 sm:grid-cols-2">
      <div><dt className="font-semibold">웹 미리보기 준비 필요</dt><dd>원본 등록 완료와 표시 파생물 생성은 별개입니다. 파생물이 생성되지 않았거나 현재 계정에 준비된 출력을 확인하지 못하면 원본의 자료 정보를 먼저 확인하세요.</dd></div>
      <div><dt className="font-semibold">원본의 유효 픽셀 영역 밖</dt><dd>원본의 NoData·마스크로 확인된 부분은 그리지 않습니다. 표시 준비 실패나 미확인 영역을 원본의 무효 영역으로 단정하지 않습니다.</dd></div>
      <div><dt className="font-semibold">준비 중</dt><dd>표시 데이터 생성 중에는 완료된 유효 부분만 보입니다. 현재 준비 상태와 사유는 창별 상태에서, 원본 메타데이터는 선택 자료 정보에서 확인할 수 있습니다.</dd></div>
      <div><dt className="font-semibold">지도 표시와 정량 분석은 별개</dt><dd>지도가 보여도 정합·수직 기준·유효영역·독립 검사점의 검증 근거가 충족되지 않으면 정량 물량을 확정하지 않습니다. 실제 분석 가능 여부와 부족한 근거는 분석·결과의 적합성 기록에서 확인하세요.</dd></div>
    </dl>
  </details>;
}
