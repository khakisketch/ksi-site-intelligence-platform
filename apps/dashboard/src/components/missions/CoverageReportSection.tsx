import type { ReactNode } from "react";

import { humanizeApiError } from "@/lib/core-api/labels";
import { summarizeCoverageCells } from "@/lib/core-api/coverage";
import type { CoreApiError } from "@/lib/core-api/client";
import type { CoverageReportView, CoverageRejectionListView } from "@/lib/core-api/types";
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
 * 거부 이력 — 이 임무에 한 건이라도 있으면 비율 타일보다 먼저 보여준다.
 * `site_status_matches_model` 관례: 모순(여기서는 "이 장비가 전에 근거 없는
 * 완료를 주장했다가 막혔다")이 결론보다 먼저 읽혀야 한다. 숫자는 안 싣는다 —
 * CoverageRejectionView 자체가 이미 숫자를 갖고 있지 않다.
 */
function RejectionHistory({ rejections }: { rejections: CoverageRejectionListView }) {
  if (rejections.rejectionCount === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-line-strong bg-sunk p-3">
      <p className="text-[12px] font-semibold break-keep text-ink-1">
        이 임무에서 서버가 거부한 완료 주장 {rejections.rejectionCount}건
      </p>
      <ul className="flex flex-col gap-1">
        {rejections.rejections.map((r, i) => (
          <li key={i} className="text-[11.5px] break-keep text-ink-2">
            {formatKoreanDateTime(r.rejectedAt, { dateStyle: "medium", timeStyle: "short" })} ·{" "}
            {r.detail ?? r.verdict}
          </li>
        ))}
      </ul>
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
 *
 * 귀속(비율은 기체 신고값)과 대사(계획 대비 초과 확인)를 분리한다(2026-08-18) —
 * 귀속은 항상 표시하고, 계획값 원 숫자는 이 캡션에 반복하지 않는다(발급 메타
 * 패널의 "계획 커버리지" 필드와 나란히 두지 않는다는 기존 원칙, page.tsx:239).
 */
export function CoverageReportSection({
  result,
  rejections,
}: {
  result: CoverageReportResult;
  rejections: CoverageRejectionListView | null;
}) {
  if (result.kind === "error") {
    const { error } = result;
    return (
      <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
    );
  }

  if (result.kind === "not-reported") {
    return (
      <>
        {rejections && <RejectionHistory rejections={rejections} />}
        <EmptyState
          title="아직 비행 보고가 도착하지 않았습니다"
          description="이 임무가 아직 비행 전이거나, 비행했지만 보고가 서버에 아직 도착하지 않았을 수 있습니다 — 이 화면만으로는 둘을 구분할 수 없습니다. 커버리지 보고는 비행한 장비만 올릴 수 있습니다."
        />
      </>
    );
  }

  const {
    latest,
    reportCount,
    reportedBy,
    recoveryRecommended,
    ratioAttributionNote,
    plannedGeneralCoverageRatio,
    plannedGeneralCoverageUnavailableReason,
  } = result.report;
  const completion = COMPLETION_STATE_LABEL[latest.summary.completionState];
  const cells = summarizeCoverageCells(latest.cells);

  return (
    <div className="flex flex-col gap-3">
      {rejections && <RejectionHistory rejections={rejections} />}

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

      {/* 귀속·대사 — 상시 텍스트(툴팁 아님). 계획값 원 숫자는 여기 안 찍는다 —
          위 "발급 메타" 패널의 "계획 커버리지" 필드를 본다(page.tsx:239 원칙). */}
      <div className="rounded-lg border border-line bg-sunk p-3">
        <p className="text-[11.5px] break-keep text-ink-2">{ratioAttributionNote}</p>
        <p className="mt-1 text-[11.5px] break-keep text-ink-muted">
          {plannedGeneralCoverageRatio !== null
            ? "계획 대비 초과 여부를 서버가 확인했습니다 — 이상 없음."
            : `대사 불가 — ${plannedGeneralCoverageUnavailableReason}`}
        </p>
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
