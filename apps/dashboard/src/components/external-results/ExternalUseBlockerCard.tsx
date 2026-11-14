import { Disclosure } from "@/components/ui/Disclosure";
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
      className="flex flex-col gap-2 rounded-lg border border-high/30 bg-high-bg p-3 text-body text-high-ink"
    >
      {intro && <p className="text-ink-2">{intro}</p>}
      <p className="text-lead font-bold break-keep">{guide.title}</p>
      <p className="break-keep">{guide.explanation}</p>
      <div className="rounded-md bg-surface/70 px-3 py-2">
        <p className="text-caption font-bold text-ink-muted">지금 할 일</p>
        <p className="mt-1 break-keep">{guide.step}</p>
        <p className="mt-1 text-caption text-ink-2">담당: {guide.ownerLabel}</p>
      </div>
      <a className="w-fit text-body font-semibold underline" href={`#${BLOCKER_TARGET_ANCHOR[guide.target]}`}>
        관련 화면으로 이동
      </a>
      <Disclosure label="식별 상세" className="text-caption text-ink-2">
        <p className="mt-1 font-mono">{guide.codes.join(", ")}</p>
      </Disclosure>
    </div>
  );
}
