import Link from "next/link";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { Disclosure } from "@/components/ui/Disclosure";
import { isAnalysisCrs } from "@/lib/geo/known-crs";
import { dataKindLabel } from "@/lib/operator-language";

import { shortDate, spokenDate } from "./areas/area-summary";
import {
  ANALYSIS_CRS_HINT,
  shortCrs,
  type CompareTimeline,
  type TimelineDimReason,
  type TimelinePoint,
  type UnorderedItem,
} from "./compare-timeline";

/**
 * 비교 모드의 "자료 날짜" 시간 띠 — 한 작업구역의 순서 있는 관측을 날짜로 놓고 이전·이후를 고른다.
 *
 * - 점을 누르면 주소만 바뀐다(GET 링크). 서버가 같은 주소 파라미터를 다시 해석·검증하므로 JS 없이도 된다.
 * - 좌표계 칩은 표시용 힌트다. 같은 좌표계인지의 판정은 Core가 다시 한다(INV-020).
 * - 흐린 점은 누를 수 없고 이유를 글자로 적는다. 색·점선만으로 구분하지 않는다.
 * - 체적·높이 차이 카드는 열려 있다고 말하지 않는다. 이 화면에는 Core의 사유 응답이 없어 일반 문구만 둔다.
 */

const DIM_LABEL: Record<TimelineDimReason, string> = {
  "no-height": "높이 자료 없음",
  "not-ready": "표시 준비 전",
  "crs-different": "좌표계 다름",
};

/** 이웃한 점 사이 최소 간격(px) — 터치 영역 44px보다 크다. */
const MIN_POINT_GAP_PX = 48;

const ROLE_LABEL = { baseline: "이전", current: "이후" } as const;
/** 조사까지 붙인 형태("이전으로"/"이후로"). */
const ROLE_AS = { baseline: "이전으로", current: "이후로" } as const;

const UNORDERED_LABEL: Record<UnorderedItem["reason"], string> = {
  "date-only": "날짜만 확인",
  unknown: "촬영 시점 미상",
  tie: "촬영 구간이 같음",
};

function swatchStyle(swatch: number | null) {
  return { background: swatch ? `var(--crs-${swatch})` : "var(--idle)" };
}

/**
 * 점의 주소 — 시간순 비교가 받는 키(mode·workAreaId·baselineAssetRef·currentAssetRef)만 싣는다.
 * 독립 보기(visualA/B)를 함께 실으면 서버가 "비교 선택 방식을 하나만 사용하세요"로 막으므로,
 * 점을 누르면 시간순 비교로 바뀌고 독립 보기 선택은 버려진다.
 */
export function pointHref(
  sitePath: string,
  workAreaId: string,
  pair: NonNullable<TimelinePoint["pair"]>,
): string {
  const query = new URLSearchParams();
  query.set("mode", "compare");
  query.set("workAreaId", workAreaId);
  query.set("baselineAssetRef", pair.baselineAssetRef);
  query.set("currentAssetRef", pair.currentAssetRef);
  return `${sitePath}?${query.toString()}`;
}

/** 점 아래 좌표계 칩. 분석 좌표계만 색을 받고 나머지는 회색이다. 글자는 항상 함께 쓴다. */
function CrsChip({ point }: { point: TimelinePoint }) {
  if (point.dimmed === "no-height") return <span className="rounded-full bg-sunk px-1.5 text-micro leading-[18px] text-ink-2">높이 자료 없음</span>;
  if (point.dimmed === "not-ready") return <span className="rounded-full bg-sunk px-1.5 text-micro leading-[18px] text-ink-2">표시 준비 전</span>;
  if (point.crs === null) return <span className="rounded-full bg-sunk px-1.5 text-micro leading-[18px] text-ink-2">좌표계 확인 전</span>;
  const code = shortCrs(point.crs);
  // 분석 밖 좌표계는 흐리지 않고 회색 칩으로만 알린다 — 분석 가능 여부는 분석 화면이 판단한다.
  const outside = !isAnalysisCrs(point.crs);
  const label = point.dimmed === "crs-different" ? `좌표계 다름 · ${code}` : outside ? `분석 밖 · ${code}` : code;
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap text-micro leading-[18px] ${point.dimmed || outside ? "rounded-full bg-sunk px-1.5 text-ink-2" : "text-ink-2"}`}>
      <i aria-hidden="true" className="inline-block size-1.5 rounded-full" style={swatchStyle(point.swatch)} />
      {label}
    </span>
  );
}

function pointLabel(point: TimelinePoint, withYear: boolean): string {
  const when = `${spokenDate(point.date, withYear)}${point.time ? ` ${point.time}` : ""}`;
  const kind = dataKindLabel(point.kind);
  const crs = point.crs ? `, 좌표계 ${shortCrs(point.crs)}` : "";
  if (point.role) return `${when}, ${kind}${crs}, ${ROLE_AS[point.role]} 선택됨`;
  if (point.dimmed) return `${when}, ${kind}, ${DIM_LABEL[point.dimmed]}${point.dimmed === "crs-different" ? ", 같은 좌표계 자료끼리만 비교" : ""}, 고를 수 없음`;
  if (point.pair && point.becomes) {
    return `${when}, ${kind}${crs}, ${ROLE_AS[point.becomes]} 고르기`;
  }
  return `${when}, ${kind}${crs}, 짝이 될 자료가 없어 고를 수 없음`;
}

function Dot({ role, dimmed }: { role: TimelinePoint["role"]; dimmed: boolean }) {
  // 모양으로도 구분한다: 이전 = 속이 빈 굵은 고리, 이후 = 채운 원, 흐림 = 점선 고리.
  if (role === "baseline") return <span aria-hidden="true" className="block size-[18px] rounded-full border-[3px] border-ink-1 bg-surface shadow-[0_0_0_4px_var(--sunk)]" />;
  if (role === "current") return <span aria-hidden="true" className="block size-[18px] rounded-full bg-ink-1 shadow-[0_0_0_4px_var(--sunk)]" />;
  if (dimmed) return <span aria-hidden="true" className="block size-3.5 rounded-full border-2 border-dashed border-idle bg-surface" />;
  return <span aria-hidden="true" className="block size-3.5 rounded-full border-2 border-ink-2 bg-surface" />;
}

function PointBlock({
  point, withYear, showYear, href,
}: { point: TimelinePoint; withYear: boolean; showYear: boolean; href: string | null }) {
  const label = pointLabel(point, withYear);
  const muted = point.dimmed !== null;
  const dot = <Dot role={point.role} dimmed={muted} />;
  const target = "flex size-11 items-center justify-center rounded-full";
  return (
    <div className="flex flex-col items-center">
      <span className="h-[18px]">
        {point.role && (
          <span className={`block rounded-full px-[7px] text-micro font-semibold leading-[16px] ${point.role === "current" ? "bg-ink-1 text-surface" : "border border-ink-1 bg-surface text-ink-1"}`}>
            {ROLE_LABEL[point.role]}
          </span>
        )}
      </span>
      {href && !muted ? (
        <Link href={href} aria-label={label} aria-current={point.role ? "true" : undefined} data-point-key={point.key} className={`${target} hover:bg-sunk focus-visible:outline-2 focus-visible:outline-offset-1`}>
          {dot}
        </Link>
      ) : (
        <button type="button" disabled aria-label={label} data-point-key={point.key} className={`${target} cursor-not-allowed`}>
          {dot}
        </button>
      )}
      {/* 해를 넘는 띠는 모든 점에 연도를 둔다 — 위 줄 연도, 아래 줄 MM-DD. 컨테이너 높이(blockHeight)가 이 줄을 포함한다. */}
      {showYear && <span aria-hidden="true" className="whitespace-nowrap text-micro leading-[14px] text-ink-muted">{point.date.slice(0, 4)}</span>}
      <span className={`whitespace-nowrap text-caption leading-[18px] ${point.role ? "font-semibold text-ink-1" : muted ? "text-ink-muted" : "text-ink-2"}`}>
        {shortDate(point.date)}{point.time ? ` ${point.time}` : ""}
      </span>
      <span className={muted ? "opacity-80" : ""}><CrsChip point={point} /></span>
    </div>
  );
}

function UnorderedRow({ items, withYear }: { items: readonly UnorderedItem[]; withYear: boolean }) {
  if (items.length === 0) return null;
  return (
    <div data-compare-unordered className="flex flex-col gap-1.5 border-t border-line pt-2">
      <h3 className="text-caption font-semibold">순서 미정 <span className="font-normal text-ink-muted">· 앞뒤를 정할 수 없어 띠에 놓지 않았습니다</span></h3>
      <ul className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <li key={item.key} className="rounded-full border border-line bg-sunk px-2 py-0.5 text-caption text-ink-2">
            {item.date ? `${spokenDate(item.date, withYear)} · ` : ""}
            {UNORDERED_LABEL[item.reason]} · {dataKindLabel(item.kind)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusCard({
  model, uploadHref, canUpload,
}: { model: CompareTimeline; uploadHref: string | null; canUpload: boolean }) {
  if (model.status === "OK") return null;
  const upload = canUpload && uploadHref ? (
    <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" inlineNotice={false}>
      <Link href={uploadHref} className="btn w-fit">높이 자료 올리기</Link>
    </ResponsiveActionBoundary>
  ) : null;
  const uploadNote = canUpload && uploadHref ? <span className="text-caption text-ink-muted lg:hidden">올리기는 노트북에서 이어서 하세요.</span> : null;
  if (model.status === "NOT_READY") {
    // 올려서 풀리는 상황이 아니다 — 올리기 안내를 두지 않고 원인을 사용자 탓으로 돌리지 않는다.
    return (
      <div data-compare-state="not-ready" role="status" className="flex flex-col gap-1.5 rounded-lg border border-line bg-sunk px-3 py-2.5">
        <p className="text-body font-semibold">표시 준비가 끝난 높이 자료가 두 개 이상 필요합니다</p>
        <p className="text-caption text-ink-2">지금 {model.notReadyCount}건이 표시 준비 전입니다. 준비되면 이 띠에서 고를 수 있습니다.</p>
      </div>
    );
  }
  if (model.status === "ONLY_ONE") {
    return (
      <div data-compare-state="only-one" role="status" className="flex flex-col gap-1.5 rounded-lg border border-line bg-sunk px-3 py-2.5">
        <p className="text-body font-semibold">{model.heightTotal === 0 ? "비교할 높이 자료가 없습니다" : "비교할 높이 자료가 하나뿐입니다"}</p>
        <p className="text-caption text-ink-2">필요한 것 · 촬영 시각이 있는 높이 자료 두 개</p>
        <div className="flex flex-wrap items-center gap-2">{upload}{uploadNote}</div>
      </div>
    );
  }
  if (model.status === "CRS_MISMATCH") {
    return (
      <div data-compare-state="crs-mismatch" role="status" className="flex flex-col gap-1.5 rounded-lg border border-line bg-sunk px-3 py-2.5">
        <p className="text-body font-semibold">좌표계 다름 · 같은 좌표계 자료끼리만 비교</p>
        <p className="text-caption text-ink-2">필요한 것 · 같은 좌표계로 기록된 높이 자료 두 개</p>
        <p className="text-micro text-ink-muted">{ANALYSIS_CRS_HINT}</p>
        <div className="flex flex-wrap items-center gap-2">{upload}{uploadNote}</div>
      </div>
    );
  }
  return (
    <div data-compare-state="no-orderable" role="status" className="flex flex-col gap-1.5 rounded-lg border border-line bg-sunk px-3 py-2.5">
      <p className="text-body font-semibold">촬영 순서가 정해진 자료가 없습니다</p>
      <p className="text-caption text-ink-2">필요한 것 · 촬영 시작·종료 시각이 기록된 높이 자료 두 개</p>
      <div className="flex flex-wrap items-center gap-2">{upload}{uploadNote}</div>
    </div>
  );
}

/** 체적·높이 차이 — 이 화면에서는 열려 있지 않다. 사유는 Core 응답 없이는 말하지 않는다. */
function VolumeNotice({ analysisHref }: { analysisHref: string | null }) {
  return (
    <div data-compare-volume="closed" className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line pt-2 text-caption text-ink-2">
      <svg aria-hidden="true" viewBox="0 0 24 24" width={13} height={13} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
        <rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" />
      </svg>
      <span className="min-w-0 break-keep">체적·높이 차이는 이 화면에서 열려 있지 않습니다. 가능 여부는 분석 화면에서 확인합니다.</span>
      {analysisHref && <Link href={analysisHref} className="tap-target inline-flex items-center underline">분석 화면에서 확인</Link>}
    </div>
  );
}

export function CompareTimeStrip({
  model, sitePath, workAreaId, uploadHref = null, canUpload = false, analysisHref = null,
}: {
  model: CompareTimeline;
  sitePath: string;
  workAreaId: string;
  uploadHref?: string | null;
  canUpload?: boolean;
  /** 분석 조건 확인 화면 — 권한이 없으면 null. */
  analysisHref?: string | null;
}) {
  if (model.slots.length === 0 && model.unordered.length === 0) return null;
  // 점 블록 높이 = 이름표 18 + 터치 영역 44 + 날짜(연도 줄 14 포함 시) + 칩 18, 여유 포함. 컨테이너는 이보다 작지 않다.
  const stack = Math.max(1, ...model.slots.map((slot) => slot.points.length));
  const blockHeight = 18 + 44 + (model.yearLabels ? 14 : 0) + 18 + 22;
  const height = stack * blockHeight + (stack - 1) * 4 + 8;
  // 점 사이 최소 간격 48px — 터치 영역(44px)이 겹치지 않게 띠의 최소 폭을 잡는다. 넘치면 띠 안에서만 가로로 민다.
  const lefts = model.slots.map((slot) => slot.leftPercent);
  const minGap = lefts.slice(1).reduce((least, value, index) => Math.min(least, value - lefts[index]!), Infinity);
  const stripMinWidth = Number.isFinite(minGap) && minGap > 0 ? Math.max(56, Math.ceil((MIN_POINT_GAP_PX * 100) / minGap)) : 56;
  const summary = model.baseline && model.current
    ? `이전 ${spokenDate(model.baseline.date, model.withYear)}, 이후 ${spokenDate(model.current.date, model.withYear)}, ${model.days === 0 ? "같은 날" : `${model.days}일 사이`}`
    : model.selectionMissing ? "선택한 두 관측이 이 띠에 없습니다" : "이전·이후를 아직 고르지 않았습니다";
  const left = model.baseline && model.current ? Math.min(...[model.baseline, model.current].map((p) => slotLeft(model, p))) : null;
  const right = model.baseline && model.current ? Math.max(...[model.baseline, model.current].map((p) => slotLeft(model, p))) : null;
  return (
    <section aria-label="자료 날짜" data-compare-timeline data-status={model.status} className="flex min-w-0 shrink-0 flex-col gap-2 rounded-lg border border-line bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-body font-semibold">자료 날짜</h2>
        {model.referenceCrs && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-sunk px-2 text-caption leading-6">
            <i aria-hidden="true" className="inline-block size-2 rounded-full" style={swatchStyle(model.referenceSwatch)} />
            {isAnalysisCrs(model.referenceCrs) ? "분석 좌표계" : "기준 좌표계 · 분석 밖"} {model.referenceCrs}
          </span>
        )}
        <span className="flex-1" />
        <p role="status" className="text-caption text-ink-2">
          <span className="sr-only">{summary}</span>
          <span aria-hidden="true">
            {model.baseline && model.current
              ? (model.days === 0 ? "같은 날" : `${model.days}일 사이`)
              : model.selectionMissing ? "선택한 두 관측이 이 띠에 없습니다"
                : model.hasPickable ? "날짜를 누르세요" : ""}
          </span>
        </p>
      </div>

      {model.slots.length > 0 && (
        <div className="overflow-x-auto overflow-y-hidden">
          <ol aria-label="촬영 날짜" className="relative mx-6" style={{ height, minWidth: `${stripMinWidth}px` }}>
            <li aria-hidden="true" className="absolute inset-x-0 top-[39px] h-0.5 bg-line-strong" />
            {left !== null && right !== null && (
              <li aria-hidden="true" data-compare-range className="absolute top-[37px] h-1.5 rounded-full bg-ink-1" style={{ left: `${left}%`, width: `${right - left}%` }} />
            )}
            {model.slots.map((slot) => (
              <li key={slot.date} data-slot-date={slot.date} className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-1" style={{ left: `${slot.leftPercent}%` }}>
                {slot.points.map((point) => (
                  <PointBlock
                    key={point.key}
                    point={point}
                    withYear={model.withYear}
                    showYear={model.yearLabels}
                    href={point.pair ? pointHref(sitePath, workAreaId, point.pair) : null}
                  />
                ))}
              </li>
            ))}
          </ol>
        </div>
      )}
      {model.hiddenCount > 0 && <p className="text-caption text-ink-muted">더 오래된 자료 {model.hiddenCount}건은 띠에 두지 않았습니다. 직접 고르기에서 찾을 수 있습니다.</p>}
      {model.reversed && <p role="status" className="text-caption text-ink-2">주소의 이전이 이후보다 늦은 날짜입니다. 누르면 시간 순서로 바로잡습니다.</p>}
      {model.selectionCrsMismatch && model.baseline?.crs && model.current?.crs && (
        <p role="status" data-compare-selection-crs className="text-caption text-ink-2">
          고른 두 자료의 좌표계가 다릅니다 · {shortCrs(model.baseline.crs)} / {shortCrs(model.current.crs)}. 같은 좌표계 자료끼리만 비교합니다.
        </p>
      )}

      <StatusCard model={model} uploadHref={uploadHref} canUpload={canUpload} />
      <UnorderedRow items={model.unordered} withYear={model.withYear} />
      <VolumeNotice analysisHref={analysisHref} />
      <Disclosure label="어떻게 하나요" className="text-caption text-ink-2">
        <p className="mt-1 leading-5">
          날짜를 누르면 이전·이후가 바뀝니다. 처음 누르면 바로 앞 날짜와 함께 보이고, 이후에는 누른 날짜와 가까운 쪽이 바뀝니다.
          흐린 날짜는 같은 좌표계의 높이 자료가 아니라 고를 수 없습니다. 순서 미정 자료는 직접 고르기에서 확인합니다.
        </p>
      </Disclosure>
    </section>
  );
}

function slotLeft(model: CompareTimeline, point: TimelinePoint): number {
  return model.slots.find((slot) => slot.points.some((item) => item.key === point.key))?.leftPercent ?? 0;
}
