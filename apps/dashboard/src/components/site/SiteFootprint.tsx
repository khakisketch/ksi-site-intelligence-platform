import type { AoiVertex } from "@/lib/core-api/types";

/**
 * 현장 표지 — 등록된 현장 경계를 어두운 계측 면 위에 선으로 그린다.
 *
 * 영상 미리보기가 없을 때(불러오는 중·없음·확인 불가·권한 없음) 같은 자리를
 * 채운다. 사진·지도 타일·합성 지형이 아니라 이미 등록된 경계 꼭짓점의 벡터
 * 표시다. 외부 요청이 없고 좌표·면적·축척을 화면에 내지 않는다 — 모양만으로
 * 현장을 알아보게 할 뿐 측량·정확도 근거가 아니다(INV-040).
 *
 * 경계가 없으면 같은 면에 현장 머리글자와 "경계 미등록"을 둔다. 경계 부재를
 * 자료 부재로 말하지 않는다.
 */

type Tone = "empty" | "loading" | "unknown" | "refused";

const CARD = { w: 320, h: 180, pad: 28 };
const ROW = { w: 56, h: 44, pad: 6 };

/** 위경도 꼭짓점을 viewBox 좌표로 옮긴다. 3개 미만이거나 넓이가 없으면 null. */
export function projectFootprint(
  vertices: readonly AoiVertex[] | null | undefined,
  box: { w: number; h: number; pad: number },
): Array<[number, number]> | null {
  if (!vertices || vertices.length < 3) return null;
  if (!vertices.every((v) => Number.isFinite(v.latDeg) && Number.isFinite(v.lonDeg))) return null;
  // 경계 중심 위도의 등장방형 근사 — 현장 규모에서 모양을 보존한다.
  const lat0 = vertices.reduce((sum, v) => sum + v.latDeg, 0) / vertices.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  const planar = vertices.map((v) => [v.lonDeg * k, v.latDeg] as const);
  const xs = planar.map(([x]) => x);
  const ys = planar.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX;
  const spanY = maxY - minY;
  if (!(spanX > 0) || !(spanY > 0)) return null;
  const scale = Math.min((box.w - box.pad * 2) / spanX, (box.h - box.pad * 2) / spanY);
  const offsetX = (box.w - spanX * scale) / 2;
  const offsetY = (box.h - spanY * scale) / 2;
  // 화면 y는 아래로 증가하므로 북쪽이 위에 오도록 뒤집는다.
  return planar.map(([x, y]) => [
    Math.round((offsetX + (x - minX) * scale) * 100) / 100,
    Math.round((box.h - offsetY - (y - minY) * scale) * 100) / 100,
  ]);
}

const CHIP_TONE: Record<Tone, string> = {
  empty: "bg-white/10 text-white/80",
  loading: "bg-white/10 text-white/80 animate-pulse",
  unknown: "bg-high-bg text-high-ink",
  refused: "bg-crit-bg text-crit-ink",
};

export function SiteFootprint({
  vertices,
  siteName,
  size = "card",
  stateLabel = null,
  note = null,
  tone = "empty",
  decorative = false,
  className = "",
}: {
  vertices: readonly AoiVertex[] | null | undefined;
  siteName: string;
  size?: "card" | "row";
  /** 미리보기 상태(불러오는 중·권한 없음 등). 있으면 칩으로 겹쳐 둔다. */
  stateLabel?: string | null;
  /** 상태의 뜻을 풀어 쓴 문장 — 접근성 이름에만 싣는다(등록 자료의 부재로 읽히지 않게). */
  note?: string | null;
  tone?: Tone;
  /** 바깥 요소가 같은 사실을 이미 말할 때 — 보조기술에서 숨긴다. */
  decorative?: boolean;
  className?: string;
}) {
  const box = size === "card" ? CARD : ROW;
  const points = projectFootprint(vertices, box);
  const mark = siteName.trim().charAt(0) || "현";
  const label =
    (points
      ? `${siteName} 등록 경계 도형. 실제 영상 미리보기가 아닙니다. 측량·정확도 근거가 아닙니다.`
      : `${siteName} 등록 경계 없음. 실제 영상 미리보기가 아닙니다.`) +
    (stateLabel ? ` ${stateLabel}.` : "") +
    (note ? ` ${note}` : "");

  return (
    <div
      {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": label })}
      data-site-visual-placeholder={tone}
      data-site-footprint={points ? "shape" : "none"}
      className={`relative overflow-hidden bg-[var(--stage)] ${size === "card" ? "aspect-[3/2] sm:aspect-[16/9]" : "h-11 w-14 shrink-0 rounded"} ${className}`}
    >
      <svg aria-hidden="true" viewBox={`0 0 ${box.w} ${box.h}`} preserveAspectRatio="xMidYMid meet" className="absolute inset-0 size-full">
        <defs>
          <pattern id={`fp-grid-${size}`} width={size === "card" ? 20 : 8} height={size === "card" ? 20 : 8} patternUnits="userSpaceOnUse">
            <path d={size === "card" ? "M20 0H0V20" : "M8 0H0V8"} fill="none" style={{ stroke: "var(--stage-grid)" }} strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={box.w} height={box.h} fill={`url(#fp-grid-${size})`} />
        {points && (
          <polygon
            points={points.map(([x, y]) => `${x},${y}`).join(" ")}
            fill="rgba(226,235,230,0.08)"
            stroke="#e2ebe6"
            strokeWidth={size === "card" ? 1.6 : 1.1}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      {!points && (
        <div className="absolute inset-0 grid place-items-center">
          <span className={`grid place-items-center rounded-md bg-white/10 font-bold text-white/85 ${size === "card" ? "size-10 text-lead" : "size-6 text-micro"}`}>
            {mark}
          </span>
        </div>
      )}
      {size === "card" && (
        <>
          <span className="absolute top-2.5 left-2.5 flex flex-wrap items-center gap-1.5">
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-micro font-semibold text-white/85">
              {points ? "등록 경계" : "경계 미등록"}
            </span>
            {stateLabel && (
              <span className={`rounded px-1.5 py-0.5 text-micro font-semibold max-sm:hidden ${CHIP_TONE[tone]}`}>{stateLabel}</span>
            )}
          </span>
          <span className="absolute right-2.5 bottom-2 text-micro text-white/55 max-sm:hidden">영상 아님</span>
        </>
      )}
    </div>
  );
}
