import type { WorkArea } from "@/lib/core-api/types";
import { partitionWorkAreas } from "@/lib/work-areas";

import { displayName, disambiguatedAreaNames } from "../site-spatial";
import { assignAreaMarks, buildAreaMap } from "./area-summary";

/**
 * 영역 탭의 지도 — 어두운 무대(`--stage`)에 사용 중 영역을 모두 그리고 고른 영역을 흰 윤곽으로 강조한다.
 *
 * 화면 표시용 그림이다. 같은 좌표계 평면의 영역만 한 지도에 올리고(나머지는 개수만 알린다),
 * 좌표를 변환하지 않는다. 경계가 분석에 맞다는 뜻이 아니다.
 * 번호·색은 목록의 같은 영역과 같다(`assignAreaMarks`). 배경 위치·현장 범위 점선은 아직 없다.
 *
 * `variant="stage"`는 넓은 화면에서 무대 자리를 채우고, `"mini"`는 좁은 화면에서 목록 위에 작게 둔다.
 */
export function SiteAreasMap({
  areas,
  selectedWorkAreaId,
  variant,
}: {
  areas: readonly WorkArea[];
  selectedWorkAreaId: string | null;
  variant: "stage" | "mini";
}) {
  const { active } = partitionWorkAreas(areas);
  const marks = assignAreaMarks(active);
  const model = buildAreaMap(areas, selectedWorkAreaId, marks);
  const names = disambiguatedAreaNames(areas);
  const selectedName = selectedWorkAreaId ? names.get(selectedWorkAreaId)?.label ?? null : null;
  const selectedShape = model.shapes.find((shape) => shape.selected) ?? null;
  const stage = variant === "stage";
  const label = [
    `영역 지도. 영역 ${active.length}개`,
    model.omitted.length > 0 ? `, 지도에 올리지 못한 영역 ${model.omitted.length}개` : "",
    selectedName && selectedShape ? `. ${selectedName} 선택됨.` : ".",
  ].join("");
  const nameWidth = selectedName ? Math.min(176, displayName(selectedName, 12).length * 12 + 18) : 0;

  return (
    <section
      aria-label="영역 지도"
      data-areas-map={variant}
      className={`relative min-w-0 overflow-hidden rounded-lg ${stage ? "h-full min-h-[320px]" : "h-44"}`}
      style={{
        backgroundColor: "var(--stage)",
        backgroundImage: "linear-gradient(var(--stage-grid) 1px, transparent 1px), linear-gradient(90deg, var(--stage-grid) 1px, transparent 1px)",
        backgroundSize: "36px 36px",
        backgroundPosition: "center",
      }}
    >
      {model.shapes.length > 0 ? (
        <svg
          role="img"
          aria-label={label}
          viewBox={`0 0 ${model.width} ${model.height}`}
          preserveAspectRatio="xMidYMid meet"
          className="absolute inset-0 block h-full w-full"
        >
          {/* 고르지 않은 영역을 먼저, 고른 영역을 마지막에 그려 윤곽이 가려지지 않게 한다. */}
          {[...model.shapes].sort((a, b) => Number(a.selected) - Number(b.selected)).map((shape) => {
            const color = shape.mark ? `var(--crs-${shape.mark.swatch})` : "var(--idle)";
            return (
              <g key={shape.workAreaId} data-area-shape={shape.workAreaId} data-selected={shape.selected ? "true" : undefined}>
                {shape.archived ? (
                  <path d={shape.d} fill="none" strokeWidth={1.6} strokeDasharray="6 4" strokeLinejoin="round" style={{ stroke: "var(--idle)" }} />
                ) : (
                  <>
                    <path d={shape.d} strokeWidth={shape.selected ? 3 : 1.6} strokeLinejoin="round" fillOpacity={shape.selected ? 0.3 : 0.16} className={shape.selected ? "stroke-white" : undefined} style={{ fill: color, ...(shape.selected ? {} : { stroke: color }) }} />
                    {shape.selected && <path d={shape.d} fill="none" strokeWidth={1.2} strokeLinejoin="round" style={{ stroke: color }} />}
                  </>
                )}
              </g>
            );
          })}
          <g fontWeight={700} fontSize={11} textAnchor="middle">
            {model.shapes.filter((shape) => shape.mark).map((shape) => (
              <g key={shape.workAreaId}>
                <circle cx={shape.labelX} cy={shape.labelY} r={shape.selected ? 12 : 10.5} strokeWidth={2} className={shape.selected ? "stroke-white" : undefined} style={{ fill: `var(--crs-${shape.mark!.swatch})`, ...(shape.selected ? {} : { stroke: "var(--stage)" }) }} />
                <text x={shape.labelX} y={shape.labelY + 4} className="fill-white">{shape.mark!.ordinal}</text>
              </g>
            ))}
          </g>
          {selectedShape && selectedName && (
            <g>
              <rect x={selectedShape.labelX - nameWidth / 2} y={selectedShape.labelY + 17} width={nameWidth} height={22} rx={6} className="fill-white" />
              <text x={selectedShape.labelX} y={selectedShape.labelY + 32} fontSize={12} fontWeight={700} textAnchor="middle" style={{ fill: "var(--stage)" }}>
                {displayName(selectedName, 12)}
              </text>
            </g>
          )}
          {stage && model.scaleBar && (
            <g fontSize={10} className="fill-white/70">
              <path d={`M${model.scaleBar.x1} ${model.scaleBar.y}H${model.scaleBar.x2}M${model.scaleBar.x1} ${model.scaleBar.y - 5}V${model.scaleBar.y + 5}M${model.scaleBar.x2} ${model.scaleBar.y - 5}V${model.scaleBar.y + 5}`} fill="none" strokeWidth={1.5} className="stroke-white/70" />
              <text x={model.scaleBar.x1} y={model.scaleBar.y - 10}>{model.scaleBar.label}</text>
            </g>
          )}
        </svg>
      ) : (
        <p role="status" className="absolute inset-0 grid place-items-center px-6 text-center text-caption text-white/70">
          {active.length === 0 ? "영역을 그리면 여기에 표시됩니다." : "지도에 올릴 수 있는 영역이 없습니다."}
        </p>
      )}

      <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap items-center gap-1.5">
        <span className="rounded-md border border-white/20 bg-black/60 px-2 py-1 text-caption text-white">영역 {active.length}개</span>
        {model.omitted.length > 0 && (
          <span data-areas-map-omitted className="rounded-md border border-white/20 bg-black/60 px-2 py-1 text-caption text-white">
            지도에 올리지 못한 영역 {model.omitted.length}개
          </span>
        )}
      </div>
      {stage && (
        <p className="absolute bottom-2 right-2 max-w-[60%] rounded-md bg-black/60 px-2 py-1 text-micro text-white/80">
          영역 경계는 화면 표시용이며 분석 적합성을 뜻하지 않습니다.
        </p>
      )}
    </section>
  );
}
