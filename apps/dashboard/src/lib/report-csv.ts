import type { DesignProgress } from "@/lib/core-api/types";

/**
 * 계획 대비 진척(M4-C) 표를 CSV 로 — 화면 표와 **같은 배열**(`DesignProgress`)에서
 * 그대로 뽑는다. 별도로 값을 다시 계산하지 않는다 — 계산이 두 곳에 있으면 화면과
 * 종이 숫자가 갈릴 수 있는 두 번째 진실이 생긴다(`design-conformance.ts` 의 지도·표
 * 원칙과 같다).
 *
 * 값은 로케일 포맷(`formatVolumeM3` 등)을 거치지 않은 **원시 숫자**를 그대로 쓴다 —
 * 콤마 천단위 구분·"m³" 단위 문자열을 CSV 칸에 넣으면 스프레드시트가 그 칸을
 * 숫자로 인식하지 못한다. 사람이 읽는 단위·서식은 화면 몫이고, 이 파일의 몫은
 * 스프레드시트가 그대로 계산에 쓸 수 있는 숫자다.
 */

/**
 * UTF-8 BOM. **지우지 않는다** — 없으면 Excel(한국어 Windows 기본 로케일)이
 * 이 파일을 CP949/EUC-KR 로 잘못 읽어 한글 헤더·구역명이 깨진다. 다른 스프레드시트
 * (Google Sheets, LibreOffice)는 BOM 유무와 무관하게 UTF-8 을 올바르게 읽으므로
 * 부작용이 없다.
 */
export const CSV_BOM = "﻿";

/** RFC 4180: 필드에 구분자·따옴표·개행이 있으면 따옴표로 감싸고 내부 따옴표는 두 배로. */
function escapeCsvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function csvRow(fields: (string | number)[]): string {
  return fields.map((field) => escapeCsvField(String(field))).join(",") + "\r\n";
}

function formatRatioForCsv(ratio: number | null): string {
  // 화면(ProgressBar)의 "해당 없음"과 같은 말 — 그 방향의 계획이 없다는 뜻이지 0%가 아니다.
  if (ratio === null) return "해당 없음";
  return (ratio * 100).toFixed(1);
}

const ZONE_HEADER = [
  "구역ID",
  "구역명",
  "계획 절토(m³)",
  "완료 절토(m³)",
  "잔여 절토(m³)",
  "절토 진척률(%)",
  "계획 성토(m³)",
  "완료 성토(m³)",
  "잔여 성토(m³)",
  "성토 진척률(%)",
  "산정 근거",
];

/**
 * 구역별 진척 표를 CSV 문자열로. 앞머리에 이 표가 무엇을 기준으로 계산됐는지
 * 적어 둔다 — 표만 떼어 돌려 보면 "언제 대비 언제"인지 알 길이 없어진다(화면의
 * "기준(원지형) … → 최신 …" 캡션과 같은 이유로 여기서도 반드시 남긴다).
 */
export function designProgressToCsv(progress: DesignProgress): string {
  let csv = CSV_BOM;
  csv += csvRow(["현장 ID", progress.siteId]);
  csv += csvRow(["설계 기준면 ID", progress.designSurfaceId]);
  csv += csvRow(["기준(원지형) 계산 시각(UTC)", progress.baselineComputedAt]);
  csv += csvRow(["최신 계산 시각(UTC)", progress.latestComputedAt]);
  csv += csvRow(["집계 제외 문턱(m)", progress.thresholdM]);
  csv += "\r\n";
  csv += csvRow(ZONE_HEADER);
  for (const zone of progress.zones) {
    csv += csvRow([
      zone.zoneId,
      zone.zoneName ?? "",
      zone.plannedCutM3,
      zone.doneCutM3,
      zone.remainingCutM3,
      formatRatioForCsv(zone.cutProgressRatio),
      zone.plannedFillM3,
      zone.doneFillM3,
      zone.remainingFillM3,
      formatRatioForCsv(zone.fillProgressRatio),
      zone.basis,
    ]);
  }
  return csv;
}
