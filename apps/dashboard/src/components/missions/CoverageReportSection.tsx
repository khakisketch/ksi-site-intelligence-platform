import type { ReactNode } from "react";

import { humanizeApiError } from "@/lib/core-api/labels";
import { summarizeCoverageCells } from "@/lib/core-api/coverage";
import type { CoreApiError } from "@/lib/core-api/client";
import type { CoverageReportView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatKoreanDateTime } from "@/lib/datetime";

import { formatRatio } from "@/app/missions/format";
import { CELL_STATE_LABEL, COMPLETION_STATE_LABEL } from "@/app/missions/mission-labels";

/** 임무 상세 화면의 "비행 결과" 섹션이 받는 조회 결과 — 서버 판정 그대로다. */
export type CoverageReportResult =
  | { kind: "reported"; report: CoverageReportView }
  | { kind: "not-reported" }
  | { kind: "error"; error: CoreApiError };

function Tile({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-line bg-surface p-3">
      <span className="break-keep text-[11px] font-semibold text-ink-2">{label}</span>
      <span className="num text-[19px] leading-tight font-bold tracking-tight">{value}</span>
    </div>
  );
}

/**
 * 임무 상세의 "비행 결과" — CoverageReport 의 존재와 서버 판정을 그대로 보여준다
 * (INV-010, PRD §15.5). 대시보드는 완료 여부를 재계산하지 않는다.
 *
 * ``not-reported`` 를 "—"로 조용히 넘기지 않는다 — 발급됐지만 아직 비행 전인지,
 * 비행했는데 보고가 아직 도착하지 않았는지는 이 화면만으로 구분되지 않는다는
 * 사실 자체가 운영자에게 필요한 정보다.
 */
export function CoverageReportSection({ result }: { result: CoverageReportResult }) {
  if (result.kind === "error") {
    const { error } = result;
    return (
      <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
    );
  }

  if (result.kind === "not-reported") {
    return (
      <EmptyState
        title="아직 비행 보고가 도착하지 않았습니다"
        description="이 임무가 아직 비행 전이거나, 비행했지만 보고가 서버에 아직 도착하지 않았을 수 있습니다 — 이 화면만으로는 둘을 구분할 수 없습니다. 커버리지 보고는 비행한 장비만 올릴 수 있습니다."
      />
    );
  }

  const { latest, reportCount, reportedBy, recoveryRecommended } = result.report;
  const completion = COMPLETION_STATE_LABEL[latest.summary.completionState];
  const cells = summarizeCoverageCells(latest.cells);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge label={completion.label} tone={completion.tone} />
        {recoveryRecommended && <StatusBadge label="재커버 권고" tone="caution" />}
        <span className="text-[12.5px] break-keep text-ink-muted">
          {formatKoreanDateTime(latest.timestamp, { dateStyle: "medium", timeStyle: "short" })} 보고 · 보고
          장비 {reportedBy ?? "확인 불가"}
        </span>
      </div>

      {recoveryRecommended && (
        <p className="text-[11.5px] break-keep text-ink-muted">
          이 임무는 미관찰 구역이 남았거나 공백이 있는 채로 종료됐습니다 — 원본 구역으로
          공간 모델 갱신(SPATIAL_REFRESH) 임무를 재발급하는 것을 고려하세요. 자동으로
          재발급되지 않습니다.
        </p>
      )}

      <div className="grid grid-cols-3 gap-2">
        <Tile label="필수 위험구역" value={formatRatio(latest.summary.mandatoryHazardRatio)} />
        <Tile label="필수 자산" value={formatRatio(latest.summary.mandatoryAssetRatio)} />
        <Tile label="접근가능 일반영역" value={formatRatio(latest.summary.accessibleGeneralRatio)} />
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Tile label="관찰됨" value={`${cells.observed} / ${cells.total}`} />
        <Tile label="미관찰(사유 있음)" value={cells.explainedGap} />
        <Tile label="미관찰(사유 없음)" value={cells.unexplainedGap} />
      </div>

      {cells.byState.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {cells.byState.map(({ state, count }) => (
            <li
              key={state}
              className="rounded-[4px] border border-line bg-sunk px-1.5 py-0.5 text-[11px] break-keep text-ink-2"
            >
              {CELL_STATE_LABEL[state]} <span className="num font-semibold">{count}</span>
            </li>
          ))}
        </ul>
      )}

      {reportCount > 1 && (
        <p className="text-[11.5px] break-keep text-ink-muted">
          이 임무에 총 <span className="num">{reportCount}</span>건의 보고가 접수됐습니다 —
          위 내용은 그중 최신 보고 기준입니다.
        </p>
      )}
    </div>
  );
}
