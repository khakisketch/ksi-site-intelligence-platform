import { BLOCKER_TARGET_ANCHOR, explainExternalUseDecision } from "@/lib/external-use-blockers";

/**
 * Explains a BLOCKED external-use decision: why it is blocked, what to do now,
 * who owns the step and where to go. Raw codes stay in the expert details.
 */
export function ExternalUseBlockerCard({
  reasons,
  remediations,
  intro,
}: {
  reasons: readonly string[];
  remediations: readonly string[];
  intro?: string;
}) {
  const guide = explainExternalUseDecision(reasons, remediations);
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-lg border border-high/30 bg-high-bg p-3 text-[13px] text-high-ink"
    >
      {intro && <p className="text-ink-2">{intro}</p>}
      <p className="text-[14px] font-bold break-keep">{guide.title}</p>
      <p className="break-keep">{guide.explanation}</p>
      <div className="rounded-md bg-surface/70 px-3 py-2">
        <p className="text-[11.5px] font-bold text-ink-muted">지금 할 일</p>
        <p className="mt-1 break-keep">{guide.step}</p>
        <p className="mt-1 text-[12px] text-ink-2">담당: {guide.ownerLabel}</p>
      </div>
      <a className="w-fit text-[12.5px] font-semibold underline" href={`#${BLOCKER_TARGET_ANCHOR[guide.target]}`}>
        관련 화면으로 이동
      </a>
      <details className="text-[12px] text-ink-2">
        <summary>전문가 정보</summary>
        <p className="mt-1 font-mono">{guide.codes.join(", ")}</p>
      </details>
    </div>
  );
}
