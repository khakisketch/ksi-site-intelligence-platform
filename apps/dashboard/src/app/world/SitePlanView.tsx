import type { EquipmentStateItem } from "@/lib/core-api/types";

/**
 * 현장 평면도 — 장비·작업자 위치를 **site_frame 좌표 그대로** 그린다.
 *
 * ## 왜 지리 지도(Leaflet basemap)가 아닌가
 *
 * `KinematicState.position` 은 현장 등록 좌표계(예: EPSG:5186)의 절대 좌표이고,
 * AOI 는 WGS84 다. 둘을 한 지도에 겹치려면 site_frame → WGS84 변환이 필요한데,
 * **그 변환은 서버만 정확히 할 수 있고(어느 CRS 인지 아는 쪽이 서버다) 이 저장소에는
 * 아직 그 경로가 없다.** 화면이 근사식으로 옮기면 그림과 숫자가 조용히 어긋난다.
 *
 * 더 중요한 이유가 있다: **CPA/TTC 는 site_frame 에서 계산된다.** 위험 판단의 근거가
 * 그 좌표계 안의 상대 기하이므로, 같은 공간에 그리면 그림이 숫자와 어긋날 수가 없다.
 * 지리 배경을 깔면 보기엔 좋지만 그 사이에 변환 한 단계가 끼고, 그 단계가 바로
 * 운영자가 판단하는 기하를 틀어놓을 수 있는 자리다.
 *
 * 지리 배경이 필요해지면 서버가 변환된 좌표를 함께 내려주는 쪽으로 여는 게 맞다.
 *
 * ## 불확실성을 원으로 그린다
 *
 * 점만 찍으면 운영자가 그 위치를 확정된 사실로 읽는다. `positionUncertaintyM` 은
 * 공분산 trace 의 제곱근(RMS 반경 근사)이고 서버가 계산한다 — 그 반경을 그대로
 * 원으로 그리면 "이만큼 흐리다"가 눈에 보인다(INV-021 의 정신을 화면으로 옮긴 것).
 */
export function SitePlanView({ entities }: { entities: EquipmentStateItem[] }) {
  if (entities.length === 0) return null;

  // 불확실성 원까지 담아야 하므로 반경을 포함해 경계를 잡는다 — 점만으로 잡으면
  // 원이 잘려 "흐림"의 크기가 화면에서 축소돼 보인다.
  const xs = entities.flatMap((e) => [
    e.state.position[0] - e.positionUncertaintyM,
    e.state.position[0] + e.positionUncertaintyM,
  ]);
  const ys = entities.flatMap((e) => [
    e.state.position[1] - e.positionUncertaintyM,
    e.state.position[1] + e.positionUncertaintyM,
  ]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  // 개체가 하나뿐이거나 전부 같은 자리면 폭이 0 이 된다 — viewBox 가 0 이면 아무것도
  // 안 보이므로 최소 20m 창을 보장한다.
  const span = Math.max(maxX - minX, maxY - minY, 20);
  const padding = span * 0.1;
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  const half = span / 2 + padding;

  // 눈금 한 칸 — 창 크기의 대략 1/4 을 1·2·5 계열로 반올림한다.
  const rawStep = (half * 2) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const scaleStepM = (normalized >= 5 ? 5 : normalized >= 2 ? 2 : 1) * magnitude;

  return (
    <figure className="flex flex-col gap-2">
      <svg
        // y 축을 뒤집는다 — site_frame 의 +y(북)는 위쪽인데 SVG 의 +y 는 아래쪽이다.
        // 뒤집지 않으면 남북이 거울처럼 반대로 그려진다.
        viewBox={`${centerX - half} ${-(centerY + half)} ${half * 2} ${half * 2}`}
        className="aspect-square w-full rounded-lg border border-line bg-sunk"
        role="img"
        aria-label={`현장 평면도 — 개체 ${entities.length}건`}
      >
        {entities.map(({ state, positionUncertaintyM }) => {
          const [x, y] = state.position;
          const [vx, vy] = state.velocity;
          const isWorker = /worker|person|작업자/i.test(state.sourceClass);
          return (
            <g key={state.entityId}>
              {/* 불확실성 반경 — 점보다 먼저 그려 뒤에 깔린다. */}
              <circle
                cx={x}
                cy={-y}
                r={positionUncertaintyM}
                className="fill-mid/10 stroke-mid/40"
                vectorEffect="non-scaling-stroke"
              />
              {/* 속도 벡터 — 1초 뒤 위치까지. 등속 가정이 CPA/TTC 와 같은 전제다. */}
              {(vx !== 0 || vy !== 0) && (
                <line
                  x1={x}
                  y1={-y}
                  x2={x + vx}
                  y2={-(y + vy)}
                  className="stroke-ink-muted"
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                />
              )}
              <circle
                cx={x}
                cy={-y}
                r={half * 0.02}
                className={isWorker ? "fill-high" : "fill-ink-1"}
              />
              <text
                x={x + half * 0.03}
                y={-y - half * 0.02}
                className="fill-ink-2"
                style={{ fontSize: half * 0.06 }}
              >
                {state.entityId}
              </text>
            </g>
          );
        })}

        {/* 축척 막대 — 좌하단. 이게 없으면 원의 크기가 몇 미터인지 알 수 없다. */}
        <g>
          <line
            x1={centerX - half + padding}
            y1={-(centerY - half + padding)}
            x2={centerX - half + padding + scaleStepM}
            y2={-(centerY - half + padding)}
            className="stroke-ink-2"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
          <text
            x={centerX - half + padding}
            y={-(centerY - half + padding) - half * 0.03}
            className="fill-ink-2"
            style={{ fontSize: half * 0.06 }}
          >
            {scaleStepM} m
          </text>
        </g>
      </svg>
      <figcaption className="text-xs text-ink-muted">
        현장 등록 좌표계({entities[0].state.siteFrame}) 평면도 · 위쪽이 +y · 옅은 원은
        위치 불확실성(RMS 반경) · 선은 1초 뒤 예상 위치(등속 가정, CPA/TTC 와 같은 전제)
      </figcaption>
    </figure>
  );
}
