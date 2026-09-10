"use client";

/** Browser printing keeps every available report section together without publishing a new artifact. */
export function PrintReportButton() {
  return (
    <button type="button" className="btn print:hidden shrink-0" onClick={() => window.print()}>
      인쇄·PDF 저장
    </button>
  );
}
