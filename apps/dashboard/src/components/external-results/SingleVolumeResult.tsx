import { StateBadge } from "@/components/ui/StatusBadge";
import { formatNumberKo } from "@/lib/core-api/phase34-labels";
import { formatKoreanDateTime } from "@/lib/datetime";

/** The Core-assigned family of a retained external volume result. */
export type ExternalVolumeKind = "EXTERNAL_RELATIVE_VOLUME" | "EXTERNAL_SINGLE_VOLUME";

/** A result without `kind` predates the single-volume family and is relative. */
export function isSingleVolumeResult(result: { kind?: ExternalVolumeKind } | null | undefined): boolean {
  return result?.kind === "EXTERNAL_SINGLE_VOLUME";
}

export function ExternalVolumeKindBadge({ single }: { single: boolean }) {
  return <StateBadge label={single ? "단일 시점 체적" : "상대 물량"} tone="neutral" />;
}

function formatNumber(value: number, maximumFractionDigits = 2): string {
  return formatNumberKo(value, maximumFractionDigits);
}

function captureRange(from: string, to: string): string {
  const start = formatKoreanDateTime(from, { dateStyle: "medium", timeStyle: "short" });
  const end = formatKoreanDateTime(to, { dateStyle: "medium", timeStyle: "short" });
  return start === end ? start : `${start} ~ ${end}`;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] font-semibold text-ink-muted">{label}</dt>
      <dd className="num mt-1 text-[18px] font-bold tracking-tight text-ink-1">{value}</dd>
    </div>
  );
}

/**
 * Core-computed single-epoch stockpile volume. Displays retained values only —
 * the dashboard never derives a volume, a baseline, or a net change here.
 */
export function SingleVolumeResult({
  fillM3,
  uncertaintyM3,
  uncertaintyNote,
  baseRoughnessM,
  boundaryValidFraction,
  capturedFrom,
  capturedTo,
}: {
  fillM3: number;
  uncertaintyM3: number | null;
  uncertaintyNote?: string | null;
  baseRoughnessM: number | null | undefined;
  boundaryValidFraction: number | null | undefined;
  /** Omit when the surrounding card already shows the target capture window. */
  capturedFrom?: string;
  capturedTo?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="체적" value={`${formatNumber(fillM3)} m³`} />
        <Metric label="불확도" value={uncertaintyM3 === null ? "불확도 미산정" : `±${formatNumber(uncertaintyM3)} m³`} />
        <Metric
          label="기저면 거칠기"
          value={baseRoughnessM === null || baseRoughnessM === undefined ? "기록 없음" : `${baseRoughnessM.toFixed(2)} m`}
        />
        <Metric
          label="경계 유효 비율"
          value={boundaryValidFraction === null || boundaryValidFraction === undefined
            ? "기록 없음"
            : `${formatNumber(boundaryValidFraction * 100, 1)}%`}
        />
      </dl>
      {uncertaintyNote && <p className="text-[11.5px] leading-4 text-ink-muted">{uncertaintyNote}</p>}
      {capturedFrom !== undefined && capturedTo !== undefined && (
        <p className="text-[12.5px] leading-5 text-ink-2">촬영 {captureRange(capturedFrom, capturedTo)}</p>
      )}
    </div>
  );
}
