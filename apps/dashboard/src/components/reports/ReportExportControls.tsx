"use client";

import { designProgressToCsv } from "@/lib/report-csv";
import type { DesignProgress } from "@/lib/core-api/types";

/**
 * 현장 보고서(M4-D) 내보내기 — "PDF로 저장"(브라우저 인쇄)과 "CSV로 내보내기".
 *
 * 둘 다 화면이 이미 렌더한 것과 **같은 1회 서버 응답**(`progress`)에서만 나온다 —
 * 인쇄는 지금 그려진 DOM 을 그대로 종이로 옮기고(`window.print()`), CSV 는 그
 * DOM 을 만든 바로 그 `DesignProgress` 를 `designProgressToCsv` 로 문자열화한다.
 * 그래서 "화면과 종이가 다른 숫자"가 구조적으로 생기지 않는다 — 별도 API 를
 * 다시 불러 값을 새로 계산하지 않는다.
 *
 * `print:hidden` 을 이 컨트롤 자체에도 건다 — 인쇄 결과물에 "인쇄" 버튼이 찍히면
 * 그 자체가 이 문서가 인쇄물이 아니라 화면 캡처라는 신호가 된다.
 */
export function ReportExportControls({
  progress,
  fileNameBase,
}: {
  progress: DesignProgress;
  fileNameBase: string;
}) {
  function handleDownloadCsv() {
    const csv = designProgressToCsv(progress);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${fileNameBase}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // click 직후 동기 해제는 일부 브라우저에서 다운로드를 취소시킨다
    // (KmzDownloadButton.tsx 와 같은 이유로 여유를 두고 해제한다).
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  }

  return (
    <div className="print:hidden flex flex-wrap gap-2">
      <button type="button" className="btn btn-primary" onClick={() => window.print()}>
        PDF로 저장(인쇄)
      </button>
      <button type="button" className="btn" onClick={handleDownloadCsv}>
        CSV로 내보내기
      </button>
    </div>
  );
}
