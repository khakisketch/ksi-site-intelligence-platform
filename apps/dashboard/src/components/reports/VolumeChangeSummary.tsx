import { formatKoreanDateTime } from "@/lib/datetime";
import {
  describeVolumeUncertainty,
  formatNetVolumeM3,
  formatVolumeM3,
} from "@/lib/core-api/phase34-labels";
import type { VolumeChangeEntry, ZoneVolumeDelta } from "@/lib/core-api/types";

/**
 * 체적 변화 요약 — 구역별 절토·성토와 **그 숫자의 한계**.
 *
 * 이 화면의 규율은 하나다: `uncertaintyM3` 가 null 이면 그 사실과 이유를 숫자
 * 옆에 붙인다(INV-024). 절토·성토를 크게 보여주고 한계를 비워두면 화면이 "이
 * 값은 믿을 만하다"고 말하는 것과 같고, 이 숫자는 정산·분쟁의 근거가 될 수
 * 있다. 기본 엔진(ODM)에는 검사점 리포트가 없어 지금은 **항상** null 이다.
 *
 * `netM3` 를 여기서 다시 계산하지 않는다 — 서버가 계약으로 검증한 값을 그대로
 * 쓴다(합산 규칙이 두 곳에 있으면 한쪽만 고쳐지는 순간 화면과 원장이 갈라진다).
 */

function ZoneRow({ zone }: { zone: ZoneVolumeDelta }) {
  const uncertainty = describeVolumeUncertainty(zone.uncertaintyM3, zone.uncertaintyNote);
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13px] font-bold break-keep">{zone.zoneId}</span>
        <span className="text-[12.5px] text-ink-2">
          면적 {zone.areaM2.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} m²
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="text-[11.5px] text-ink-2">절토</p>
          <p className="text-[15px] font-bold tabular-nums">{formatVolumeM3(zone.cutM3)}</p>
        </div>
        <div>
          <p className="text-[11.5px] text-ink-2">성토</p>
          <p className="text-[15px] font-bold tabular-nums">{formatVolumeM3(zone.fillM3)}</p>
        </div>
        <div>
          <p className="text-[11.5px] text-ink-2">순변화</p>
          <p className="text-[15px] font-bold tabular-nums">
            {formatNetVolumeM3(zone.netM3)}
          </p>
        </div>
      </div>

      <p className="text-[12px] text-ink-muted break-keep">
        {zone.thresholdM} m 미만의 표고차는 재구성 노이즈로 보고 세지 않았습니다.
      </p>

      {/* 이 블록이 이 컴포넌트의 존재 이유다 — 숫자만 보여주고 한계를 감추지 않는다.
          "없으면 미산출이라고 말한다"는 규칙 자체는 phase34-labels 가 소유한다. */}
      <p
        className={
          uncertainty.missing
            ? "rounded-md border border-line-strong bg-sunk px-2.5 py-2 text-[12.5px] break-keep text-ink-2"
            : "text-[12.5px] break-keep text-ink-2"
        }
        data-testid={uncertainty.missing ? "uncertainty-missing" : "uncertainty-value"}
      >
        {uncertainty.text}
      </p>
    </li>
  );
}

export function VolumeChangeSummary({
  entry,
  totalNetM3,
}: {
  entry: VolumeChangeEntry;
  /** 서버가 계산한 최신 리포트의 전 구역 순변화. */
  totalNetM3: number | null;
}) {
  const { report } = entry;
  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[15px] font-bold break-keep">구역별 토공 변화</h2>
          {totalNetM3 !== null && (
            <span className="text-[13px] tabular-nums">
              전체 순변화 {formatNetVolumeM3(totalNetM3)}
            </span>
          )}
        </div>
        <p className="text-[12.5px] text-ink-2 break-keep">
          {formatKoreanDateTime(report.computedAt)} 계산 · 좌표계{" "}
          {report.crs}
        </p>
      </header>

      {/* 수직기준을 숨기지 않는다 — 타원체고와 정표고는 국내에서 20~30m 차이가
          나고, 어느 쪽인지가 이 숫자의 의미를 바꾼다. */}
      {report.verticalDatum === "ellipsoidal_native" && (
        <p className="rounded-md border border-line bg-sunk px-2.5 py-2 text-[12.5px] break-keep text-ink-2">
          표고 기준이 <strong className="font-bold">타원체고(지오이드 미적용)</strong>
          입니다. 같은 파이프라인으로 만든 두 시점의 <strong className="font-bold">
          상대 변화</strong>만 유효하며, 설계 계획고와 직접 비교할 수 없습니다.
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {report.zones.map((zone) => (
          <ZoneRow key={zone.zoneId} zone={zone} />
        ))}
      </ul>

      <p className="text-[12px] text-ink-muted break-keep">
        비교 대상: {report.baseline.artifactId}({report.baseline.jobId}) →{" "}
        {report.current.artifactId}({report.current.jobId})
      </p>
    </section>
  );
}
