import { COMPLETION_STATE_LABEL, PROCESSING_JOB_STATUS_LABEL } from "@/app/missions/mission-labels";
import type { CoverageReportResult } from "@/components/missions/CoverageReportSection";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { ProcessingJobSummary, SourceMediaBundleView } from "@/lib/core-api/types";

type StageTone = "done" | "active" | "waiting" | "warning";

type Stage = {
  title: string;
  detail: string;
  tone: StageTone;
};

type MissionLifecycleInput = {
  coverage: CoverageReportResult;
  bundle: SourceMediaBundleView | null;
  latestJob: ProcessingJobSummary | null;
  hasComparisonReport: boolean;
};

function stageClass(tone: StageTone): string {
  switch (tone) {
    case "done":
      return "border-safe bg-safe-bg text-safe-ink";
    case "active":
      return "border-accent bg-accent-tint text-ink-1";
    case "warning":
      return "border-high bg-high-bg text-high-ink";
    default:
      return "border-line bg-surface text-ink-2";
  }
}

function stageLabel(tone: StageTone): string {
  if (tone === "done") return "확인됨";
  if (tone === "active") return "진행 중";
  if (tone === "warning") return "확인 필요";
  return "대기";
}

/**
 * 서버가 실제로 보고한 상태만 운영 흐름에 반영한다. coverage가 없다는 사실만으로
 * 비행 전·비행 중·실패 중 어느 것도 단정하지 않는다(INV-010).
 */
export function deriveMissionStages({
  coverage,
  bundle,
  latestJob,
  hasComparisonReport,
}: MissionLifecycleInput): Stage[] {
  const coverageStage: Stage =
    coverage.kind === "reported"
      ? {
          title: "비행 결과",
          detail: COMPLETION_STATE_LABEL[coverage.report.latest.summary.completionState].label,
          tone:
            coverage.report.latest.summary.completionState === "COMPLETED"
              ? "done"
              : "warning",
        }
      : coverage.kind === "error"
        ? { title: "비행 결과", detail: "조회하지 못했습니다", tone: "warning" }
        : {
            title: "비행 결과",
            detail: "비행 보고 대기",
            tone: "waiting",
          };

  const sourceStage: Stage = !bundle
    ? { title: "사진 묶음", detail: "아직 등록된 사진 없음", tone: "waiting" }
    : bundle.status === "SEALED"
      ? { title: "사진 묶음", detail: `${bundle.mediaCount}장 봉인됨`, tone: "done" }
      : { title: "사진 묶음", detail: `${bundle.mediaCount}장 · 봉인 전`, tone: "active" };

  const processingLabel = latestJob ? PROCESSING_JOB_STATUS_LABEL[latestJob.status] : null;
  const processingStage: Stage = !latestJob
    ? { title: "재구성", detail: "아직 발행되지 않음", tone: "waiting" }
    : latestJob.status === "SUCCEEDED"
      ? { title: "재구성", detail: "완료", tone: "done" }
      : latestJob.status === "FAILED" || latestJob.status === "CANCELLED"
        ? { title: "재구성", detail: processingLabel?.label ?? latestJob.status, tone: "warning" }
        : { title: "재구성", detail: processingLabel?.label ?? latestJob.status, tone: "active" };

  const analysisStage: Stage = hasComparisonReport
    ? { title: "비교·리포트", detail: "결과 있음", tone: "done" }
    : { title: "비교·리포트", detail: "두 시점 비교 전", tone: "waiting" };

  return [
    { title: "계약", detail: "발급됨", tone: "done" },
    coverageStage,
    sourceStage,
    processingStage,
    analysisStage,
  ];
}

/**
 * 임무는 단순히 발급된 계약이 아니라 이후 비행 결과·사진·처리·비교로 이어지는
 * 작업이다. 이 컴포넌트는 없는 stage를 완료처럼 보이게 하지 않는다. 특히 coverage가
 * 없으면 "비행 전"이라고 추측하지 않고 "비행 보고 대기"라고만 말한다(INV-010).
 */
export function MissionLifecycle(input: MissionLifecycleInput) {
  const stages = deriveMissionStages(input);

  return (
    <section className="rounded-lg border border-line bg-surface p-4" aria-labelledby="mission-lifecycle-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 id="mission-lifecycle-title" className="text-[14px] font-bold tracking-tight break-keep">
            임무 진행 상황
          </h2>
          <p className="mt-0.5 text-[12px] break-keep text-ink-muted">
            계약 이후의 사실을 순서대로 보여줍니다. 표시되지 않은 단계는 아직 확인되지 않았습니다.
          </p>
        </div>
      </div>
      <ol className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-5">
        {stages.map((stage, index) => (
          <li key={stage.title} className={`rounded-md border p-2.5 ${stageClass(stage.tone)}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="num text-[10.5px] font-bold">{index + 1}</span>
              <StatusBadge label={stageLabel(stage.tone)} tone={stage.tone === "warning" ? "warning" : stage.tone === "done" ? "positive" : stage.tone === "active" ? "progress" : "neutral"} />
            </div>
            <p className="mt-2 text-[12.5px] font-semibold break-keep">{stage.title}</p>
            <p className="mt-0.5 text-[11.5px] break-keep">{stage.detail}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
