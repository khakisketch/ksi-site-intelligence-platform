"use client";

import { slotMismatch, type ArtifactSlot, type GeoTiffRecognition } from "@/lib/geo/geotiff-header";
import { formatCountKo, formatSignificantKo } from "@/lib/number-format";

export type HeaderRecognitionState =
  | { status: "recognized"; value: GeoTiffRecognition }
  | { status: "not-geotiff" };

const SLOT_LABEL: Record<ArtifactSlot, string> = { ortho: "정사영상", dsm: "DSM" };

function formatPixelSize([x, y]: [number, number]): string {
  const digits = (value: number) => formatSignificantKo(value, 4);
  return x === y ? digits(x) : `${digits(x)} × ${digits(y)}`;
}

/**
 * AX-3: 한 칸(정사영상/DSM)의 헤더 인식 결과와 좌표계 신고 입력.
 * 여기 보이는 값은 모두 고객 신고 또는 참고값이다. 측정 사실은 봉인 뒤 KSI 검사가 만든다.
 */
export function ExternalHeaderRecognition({ slot, state, crs, onCrsChange, crsLocked, resumingRegistered }: {
  slot: ArtifactSlot;
  state: HeaderRecognitionState;
  crs: string;
  onCrsChange: (value: string) => void;
  crsLocked: boolean;
  /** 재개는 등록된 신고를 다시 보내지 않으므로 새 좌표계 신고 칸을 보이지 않는다. */
  resumingRegistered: boolean;
}) {
  const label = SLOT_LABEL[slot];
  if (state.status === "not-geotiff") {
    return <p role="alert" className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12px] text-high-ink">
      {label} 파일에서 GeoTIFF 헤더를 읽지 못했습니다. 올바른 파일인지 확인하세요. 등록하면 KSI 검사에서 형식을 다시 확인합니다.
    </p>;
  }
  const value = state.value;
  const other = slot === "ortho" ? "dsm" : "ortho";
  return <div className="flex flex-col gap-2 rounded-lg border border-line bg-sunk p-3 text-[12px]">
    <p className="text-ink-2">파일 헤더에서 읽은 {label} 정보입니다. 신고값이며, 등록 후 KSI 검사로 확인합니다.</p>
    {slotMismatch(slot, value.kindHint) && <p role="alert" className="text-high-ink">
      이 파일은 {SLOT_LABEL[other]}처럼 보입니다({value.kindHint === "dsm" ? "단일 실수 밴드" : "8비트 컬러 밴드"}). 올바른 칸에 넣었는지 확인하세요.
    </p>}
    {resumingRegistered
      ? <p className="text-ink-2">이미 등록된 신고를 그대로 사용합니다. 헤더 {value.declaredCrs ? `좌표계 ${value.declaredCrs}` : "정보"}는 참고로만 보여줍니다.</p>
      : <>
        <label className="flex flex-col gap-1 font-semibold">
          {label} 좌표계 신고
          <input className="input" aria-label={`${label} 좌표계 신고`} placeholder="예: EPSG:5186 (모르면 비워 두세요)" value={crs} disabled={crsLocked} maxLength={255} onChange={(event) => onCrsChange(event.target.value)} />
        </label>
        {value.declaredCrs === null && <p className="text-ink-2">헤더에 EPSG 좌표계가 없습니다. 알고 있는 경우에만 입력하세요.</p>}
      </>}
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-ink-2">
      <dt>크기</dt><dd>{formatCountKo(value.width)} × {formatCountKo(value.height)} 픽셀</dd>
      {value.pixelSize && <><dt>픽셀 크기</dt><dd>{formatPixelSize(value.pixelSize)} (좌표계 단위, 참고)</dd></>}
      {value.producer && <><dt>생산 소프트웨어</dt><dd>{value.producer.name}{value.producer.version ? ` ${value.producer.version}` : ""} (비어 있는 소프트웨어 칸에만 채움)</dd></>}
      {value.headerDateTime && <><dt>헤더 날짜</dt><dd>{value.headerDateTime} (참고: 소프트웨어에 따라 촬영 시각 또는 파일 생성 시각)</dd></>}
    </dl>
  </div>;
}
