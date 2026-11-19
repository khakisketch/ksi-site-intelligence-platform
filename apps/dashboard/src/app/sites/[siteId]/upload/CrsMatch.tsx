import type { ReactNode } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { assignCrsSwatches, type CrsGroup, type CrsMatch as CrsMatchView, type CrsMatchVerdict } from "@/lib/crs-match";
import { isAnalysisCrs, wgs84UtmZoneOf } from "@/lib/geo/known-crs";
import { crsName } from "@/lib/measurement-profile";

/**
 * 올리는 DSM의 좌표계를 같은 구역에 이미 있는 DSM과 나란히 놓고 "비교가 되는지"를 한눈에 보인다.
 * 표시만 한다 — 막지 않고, 자동 변환도 하지 않는다. 비교 허용 여부는 Core가 같은 좌표계인지 다시 확인한다.
 */

type Tone = "safe" | "high" | "mid" | "idle";

const BAND: Record<Tone, string> = {
  safe: "bg-safe-bg text-safe-ink",
  high: "bg-high-bg text-high-ink",
  mid: "bg-mid-bg text-mid-ink",
  idle: "bg-idle-bg text-idle-ink",
};

function bandOf(match: CrsMatchView): { tone: Tone; mark: "yes" | "no" | "some" | "none"; text: string } {
  const { total, sameCount } = match;
  const verdicts: Record<CrsMatchVerdict, { tone: Tone; mark: "yes" | "no" | "some" | "none"; text: string }> = {
    first: { tone: "idle", mark: "none", text: "이 구역의 첫 DSM입니다" },
    same: { tone: "safe", mark: "yes", text: `이 구역 DSM ${total}건과 비교할 수 있습니다` },
    different: { tone: "high", mark: "no", text: `이 구역 DSM ${total}건과 좌표계가 달라 비교할 수 없습니다` },
    mixed: { tone: "mid", mark: "some", text: `같은 좌표계 ${sameCount}건 · 다른 좌표계 ${total - sameCount}건` },
    "not-analysis": { tone: "high", mark: "no", text: "분석에 쓰지 않는 좌표계입니다. 보기와 올리기만 됩니다" },
  };
  return verdicts[match.verdict];
}

/** 문장이 뜻을 이미 전하는 곳(상태 띠)에서는 decorative로 써 같은 말을 두 번 읽지 않게 한다. */
function Mark({ kind, decorative = false }: { kind: "yes" | "no" | "some" | "none"; decorative?: boolean }) {
  const label = kind === "yes" ? "같은 좌표계" : kind === "no" ? "다른 좌표계" : kind === "some" ? "일부만 같음" : "비교할 자료 없음";
  const path =
    kind === "yes" ? <path d="m4.5 10.5 3.5 3.5 7.5-8" /> : kind === "no" ? <path d="m6 6 8 8M14 6l-8 8" /> : <path d="M5 10h10" />;
  return (
    <svg {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": label })} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="size-4 shrink-0">
      {!decorative && <title>{label}</title>}
      {path}
    </svg>
  );
}

const monthDay = (iso: string | null): string | null => {
  const match = iso ? /^\d{4}-(\d{2})-(\d{2})/.exec(iso) : null;
  return match ? `${Number(match[1])}/${Number(match[2])}` : null;
};

function rangeOf(group: CrsGroup): string | null {
  const first = monthDay(group.firstDate);
  const last = monthDay(group.lastDate);
  if (!first) return null;
  return last && last !== first ? `${first}~${last}` : first;
}

function Tile({ swatch, eyebrow, crs, detail, mark }: { swatch: number | null; eyebrow?: string; crs: string; detail?: string | null; mark?: ReactNode }) {
  const name = crsName(crs);
  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-line bg-sunk px-2.5 py-2">
      <span aria-hidden="true" className="h-9 w-1.5 shrink-0 rounded-full" style={{ background: swatch ? `var(--crs-${swatch})` : "var(--idle)" }} />
      <div className="min-w-0 flex-1">
        {eyebrow && <p className="text-caption font-semibold text-ink-muted">{eyebrow}</p>}
        <p className="truncate text-body font-semibold">{name ?? crs}</p>
        <p className="truncate text-caption text-ink-muted">{[name ? crs : null, detail].filter(Boolean).join(" · ") || " "}</p>
      </div>
      {mark}
    </div>
  );
}

/** 공식 문서에서 확인한 좌표계 지정 위치만 적는다. 이미 만든 결과를 다시 쓸 수 있는지는 프로그램마다 달라 문서 확인을 안내한다. */
const EXPORT_GUIDE: ReadonlyArray<{ program: string; where: string }> = [
  { program: "DJI Terra", where: "좌표계 설정(Coordinate System Settings) → 알려진 좌표계에서 수평 좌표 참조 시스템 선택" },
  { program: "PIX4Dmapper", where: "Project → Select Output Coordinate System… → Known Coordinate System → Advanced Coordinate Options → From EPSG…" },
  { program: "Metashape", where: "File → Export → Export DEM… 대화상자에서 좌표계 지정" },
];

export function CrsMatch({ match }: { match: CrsMatchView }) {
  const band = bandOf(match);
  // 범주 색은 분석에 쓰는 좌표계에만 준다. 비교할 수 없는 좌표계는 회색이다(자료 표와 같은 규칙).
  const swatches = assignCrsSwatches([...match.groups.map((group) => group.crs), match.fileCrs].filter(isAnalysisCrs));
  const fileSwatch = swatches.get(match.fileCrs) ?? null;
  const target = match.groups[0] && isAnalysisCrs(match.groups[0].crs) ? match.groups[0].crs : "EPSG:5186";
  const targetName = crsName(target);
  const needsGuide = match.verdict === "different" || match.verdict === "mixed" || match.verdict === "not-analysis";
  const utmDefault = wgs84UtmZoneOf(match.fileCrs) !== null && match.verdict !== "same";

  return (
    <div data-crs-match={match.verdict} aria-label="좌표계 대조" role="group" className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
      <Tile swatch={fileSwatch} eyebrow="이 파일" crs={match.fileCrs} />
      {match.groups.length > 0 && (
        <>
          <p className="flex items-center gap-1.5 px-1 text-caption text-ink-muted" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="size-3"><path d="M8 3v10m0 0-3-3m3 3 3-3" /></svg>
            이 구역에 있는 DSM
          </p>
          <ul className="flex flex-col gap-1.5" aria-label="이 구역에 있는 DSM의 좌표계">
            {match.groups.map((group) => (
              <li key={group.crs}>
                <Tile
                  swatch={swatches.get(group.crs) ?? null}
                  crs={group.crs}
                  detail={[`${group.count}건`, rangeOf(group)].filter(Boolean).join(" · ")}
                  mark={<span className={`inline-flex rounded-full p-1 ${group.same && match.verdict !== "not-analysis" ? "bg-safe-bg text-safe-ink" : "bg-high-bg text-high-ink"}`}><Mark kind={group.same && match.verdict !== "not-analysis" ? "yes" : "no"} /></span>}
                />
              </li>
            ))}
          </ul>
        </>
      )}
      <p role="status" className={`flex items-center gap-2 rounded-lg px-3 py-2 text-body font-semibold ${BAND[band.tone]}`}>
        <Mark kind={band.mark} decorative />
        <span className="min-w-0">{band.text}</span>
      </p>
      {match.truncated && match.verdict !== "not-analysis" && <p className="px-1 text-caption text-ink-muted">최근 50건 기준입니다. 더 오래된 자료는 포함하지 않았습니다.</p>}
      {needsGuide && (
        <Disclosure label="어떻게 하면 되나요" className="rounded-lg border border-line px-3">
          <div className="flex flex-col gap-2 pb-3 text-caption leading-5 text-ink-2">
            {match.verdict === "not-analysis" ? (
              <p>올리고 지도에서 볼 수 있습니다. 높이·단면·비교에 쓰는 좌표계는 한국 평면직각 5종(EPSG:5179·5185~5188)과 WGS84 UTM 51N·52N입니다.</p>
            ) : (
              <p>이 파일만으로 보기·높이·단면은 됩니다. 비교와 체적은 좌표계가 같은 자료끼리만 합니다. 자동으로 바꾸지 않습니다.</p>
            )}
            {utmDefault && <p>WGS84 UTM은 출력 좌표계를 따로 정하지 않았을 때 프로그램이 정하는 기본값입니다.</p>}
            <p className="font-semibold text-ink-1">{targetName ? `${targetName} · ${target}` : target}으로 다시 내보내려면</p>
            <ul className="flex flex-col gap-1.5">
              {EXPORT_GUIDE.map((item) => (
                <li key={item.program} className="grid grid-cols-[88px_minmax(0,1fr)] gap-2">
                  <span className="font-semibold text-ink-1">{item.program}</span>
                  <span className="[overflow-wrap:anywhere]">{item.where}</span>
                </li>
              ))}
            </ul>
            <p className="text-ink-muted">이미 만든 결과의 좌표계만 바꿔 내보낼 수 있는지는 프로그램마다 다릅니다. 해당 프로그램 문서를 확인하세요.</p>
          </div>
        </Disclosure>
      )}
    </div>
  );
}
