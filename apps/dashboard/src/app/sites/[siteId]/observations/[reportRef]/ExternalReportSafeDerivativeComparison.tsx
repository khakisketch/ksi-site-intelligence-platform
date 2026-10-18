"use client";

import { useState } from "react";

import { ExternalSanitizedOrthophoto } from "@/app/field/ExternalSanitizedOrthophoto";
import type { ExactReportSafeDerivativePair, ExactSafeDerivative } from "@/lib/external-report-display-types";
import { formatKoreanDateTime } from "@/lib/datetime";

function capturedRange(subject: ExactSafeDerivative): string {
  const start = formatKoreanDateTime(subject.capturedFrom, { dateStyle: "short", timeStyle: "short" });
  const end = formatKoreanDateTime(subject.capturedTo, { dateStyle: "short", timeStyle: "short" });
  return start === end ? start : `${start} ~ ${end}`;
}

function SafeDerivative({ label, subject, onDismiss }: {
  label: string;
  subject: ExactSafeDerivative;
  onDismiss: () => void;
}) {
  return <article className="min-w-0 rounded-lg border border-line bg-surface p-3">
    <h3 className="text-[14px] font-semibold">{label}</h3>
    <p className="mt-1 text-[12px] leading-5 text-ink-2">촬영 {capturedRange(subject)}</p>
    <ExternalSanitizedOrthophoto
      workOrderId={subject.workOrderId}
      submissionRef={subject.submissionRef}
      revision={subject.revision}
      sanitizedDisplayRef={subject.sanitizedDisplayRef}
      receiptDigest={subject.receiptDigest}
      onDismiss={onDismiss}
    />
  </article>;
}

/** This view has no raster analysis path: it opens only re-bound display derivatives. */
export function ExternalReportSafeDerivativeComparison({ pair }: { pair: ExactReportSafeDerivativePair }) {
  const [visible, setVisible] = useState(false);
  return <section className="rounded-xl border border-line bg-surface p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-[16px] font-bold tracking-tight">기준·현재 표시용 정사영상</h2>
        <p className="mt-1 max-w-3xl text-[13px] leading-5 text-ink-2">보고서에 보관된 기준과 현재 관측에 다시 결속된 표시용 파생본만 나란히 확인할 수 있습니다. 이 화면은 공간 차이·열지도·새 물량 수치를 만들지 않습니다.</p>
      </div>
      {pair.state === "READY" && <button className="btn w-fit" onClick={() => setVisible((current) => !current)}>{visible ? "표시용 정사영상 닫기" : "기준·현재 표시용 정사영상 보기"}</button>}
    </div>
    {pair.state === "UNAVAILABLE" ? <p role="status" className="mt-3 rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] leading-5 text-ink-2">{pair.reason} 원본 파일이나 추정 표시를 대신 열지 않습니다.</p> : visible && <div className="mt-3 grid gap-3 xl:grid-cols-2"><SafeDerivative label="기준 관측" subject={pair.baseline} onDismiss={() => setVisible(false)} /><SafeDerivative label="현재 관측" subject={pair.current} onDismiss={() => setVisible(false)} /></div>}
  </section>;
}
