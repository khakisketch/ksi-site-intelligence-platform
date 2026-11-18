"use client";

import { slotMismatch, type ArtifactSlot, type GeoTiffRecognition } from "@/lib/geo/geotiff-header";
import { sortFindings, type PreflightFinding, type PreflightLevel } from "@/lib/geo/geotiff-preflight";
import { formatCountKo, formatSignificantKo } from "@/lib/number-format";

export type HeaderRecognitionState =
  | { status: "recognized"; value: GeoTiffRecognition; findings?: readonly PreflightFinding[] }
  | { status: "not-geotiff" };

const SLOT_LABEL: Record<ArtifactSlot, string> = { ortho: "정사영상", dsm: "DSM" };

function formatPixelSize([x, y]: [number, number]): string {
  const digits = (value: number) => formatSignificantKo(value, 4);
  return x === y ? digits(x) : `${digits(x)} × ${digits(y)}`;
}

const LEVEL_TAG: Record<PreflightLevel, string> = { blocked: "검사에서 거부 예상", may: "거부될 수 있음", notice: "참고" };

/**
 * 올리기 전 점검 결과. 판정이 아니라 안내이며 등록을 막지 않는다. 파일 구조 문제가 있으면
 * 큰 파일을 올리기 전에 알 수 있도록 맨 위에 둔다.
 */
function PreflightList({ label, findings }: { label: string; findings: readonly PreflightFinding[] }) {
  const sorted = sortFindings(findings);
  const severe = sorted.some((finding) => finding.level === "blocked");
  return <div role={severe ? "alert" : "status"} aria-label={`${label} 올리기 전 점검`} className="flex flex-col gap-1 rounded-lg border border-line bg-surface px-3 py-2">
    <p className={severe ? "font-semibold text-high-ink" : "font-semibold"}>
      {severe ? `이 ${label} 파일은 올려도 검사에서 거부될 가능성이 높습니다.` : `올리기 전 확인할 점이 있습니다.`}
    </p>
    <ul className="flex flex-col gap-1.5">
      {sorted.map((finding) => <li key={finding.code} className="leading-5">
        <span className="mr-1.5 rounded border border-line px-1.5 py-px text-micro font-semibold text-ink-2">{LEVEL_TAG[finding.level]}</span>
        {finding.title}
        {finding.fix && <span className="block text-ink-2">→ {finding.fix}</span>}
      </li>)}
    </ul>
    <p className="text-micro text-ink-muted">파일 앞부분만 읽은 안내이며, 등록 뒤 KSI 검사가 최종 확인합니다.</p>
  </div>;
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
    return <p role="alert" className="rounded-lg border border-line bg-sunk px-3 py-2 text-caption text-high-ink">
      {label} 파일에서 GeoTIFF 헤더를 읽지 못했습니다. 올바른 파일인지 확인하세요. 등록하면 KSI 검사에서 형식을 다시 확인합니다.
    </p>;
  }
  const value = state.value;
  const other = slot === "ortho" ? "dsm" : "ortho";
  return <div className="flex flex-col gap-2 rounded-lg border border-line bg-sunk p-3 text-caption">
    {!resumingRegistered && state.findings && state.findings.length > 0 && <PreflightList label={label} findings={state.findings} />}
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
      {value.producer && <><dt>TIFF Software 태그</dt><dd>{value.producer.name}{value.producer.version ? ` ${value.producer.version}` : ""} (참고: 내보내기 도구일 수 있어 재구성 제작자로 단정하지 않습니다)</dd></>}
      {value.headerDateTime && <><dt>헤더 날짜</dt><dd>{value.headerDateTime} (참고: 소프트웨어에 따라 촬영 시각 또는 파일 생성 시각)</dd></>}
    </dl>
  </div>;
}
