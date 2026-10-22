"use client";

import Link from "next/link";
import { createContext, useContext, useMemo, type ReactNode } from "react";

import {
  sanitizeSiteVisualTileDescriptor,
  visualTileAccessibleName,
  visualTileCountLine,
  visualTileFactLine,
  type SiteVisualTileDescriptor,
} from "@/lib/site-visual-tile";

/**
 * 현장 목록 합성 타일 — 실제 픽셀이 없을 때의 작은 범위 도식.
 *
 * 보이는 복셀·위성사진이 아니다. 평면 벡터(등록된 작업구역 경계 1개, 원본
 * 좌표 숫자 그대로)와 짧은 등록 사실(종류·촬영 구간·건수)만 말한다.
 * 사진처럼 보이는 덧칠(그라데이션·음영·지형 흉내·위성 흉내 래스터)은 두지
 * 않는다. 조작(확대·이동·폼)이 없고, 링크는 이 타일이 보여주는 구역이 실제로
 * 있는 현장 주소로만 간다(미리보기 열기를 가장하지 않는다).
 *
 * 타일 기술서는 현장 목록 페이지(서버, 같은 세션 집계)가
 * `SiteVisualTileProvider` 로 내려준다. `SitePreviewThumb` 은 기술서를 다시
 * 검증한 뒤, 실제 픽셀 미리보기가 없을 때만 이 타일을 그린다.
 */

const SiteVisualTileMapContext = createContext<Readonly<Record<string, unknown>> | null>(null);

export function SiteVisualTileProvider({
  tiles,
  children,
}: {
  tiles: Readonly<Record<string, unknown>>;
  children: ReactNode;
}) {
  return (
    <SiteVisualTileMapContext.Provider value={tiles}>
      {children}
    </SiteVisualTileMapContext.Provider>
  );
}

/**
 * 이 현장의 합성 기술서 — 검증된 것만 돌린다. 없거나 어긋나면 null이다.
 *
 * 검증 결과는 `useMemo`로 고정한다. 검증기가 매 호출마다 새 객체를 만들면
 * 호출자는 이 값이 의존성으로 든 effect를 렌더마다 다시 돌리게 된다 —
 * 참조만 바뀌는데 작업이 계속 재시작되는 순환이 생긴다. 원본 기술서
 * 객체(`tiles[siteId]`)가 그대로일 때만 새 참조가 생긴다.
 */
export function useSiteVisualTile(siteId: string): SiteVisualTileDescriptor | null {
  const tiles = useContext(SiteVisualTileMapContext);
  const raw = tiles ? (tiles[siteId] ?? null) : null;
  return useMemo(() => sanitizeSiteVisualTileDescriptor(raw, siteId), [raw, siteId]);
}

interface PlaneBounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function ringBounds(ring: ReadonlyArray<readonly [number, number]>): PlaneBounds | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of ring) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) {
    return null;
  }
  return { minX, minY, maxX, maxY };
}

/**
 * 링의 화면 viewBox — 원본 숫자를 그대로 쓰고 y만 뒤집는다(표시용 view
 * 맞춤, 좌표 변환 아님). 한 축에 눌린 링도 0으로 나누지 않고 그린다.
 */
function visualTileViewBox(ring: ReadonlyArray<readonly [number, number]>): string | null {
  const bounds = ringBounds(ring);
  if (!bounds) return null;
  const spanX = bounds.maxX - bounds.minX;
  const spanY = bounds.maxY - bounds.minY;
  const reference = spanX > 0 ? spanX : spanY > 0 ? spanY : 1;
  const padX = spanX === 0 ? reference * 0.08 : spanX * 0.08;
  const padY = spanY === 0 ? reference * 0.08 : spanY * 0.08;
  return `${bounds.minX - padX} ${-(bounds.maxY + padY)} ${spanX + padX * 2} ${spanY + padY * 2}`;
}

function RingPolygon({ tile }: { tile: SiteVisualTileDescriptor }) {
  const viewBox = visualTileViewBox(tile.ring);
  if (!viewBox) return null;
  const points = tile.ring.map(([x, y]) => `${x},${y}`).join(" ");
  return (
    <svg
      viewBox={viewBox}
      preserveAspectRatio="xMidYMid meet"
      className="block size-full text-ink-2"
      aria-hidden="true"
      focusable="false"
    >
      <g transform="scale(1,-1)">
        <polygon
          points={points}
          fill="currentColor"
          fillOpacity={0.08}
          stroke="currentColor"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  );
}

export function SiteVisualTile({ tile, size }: { tile: SiteVisualTileDescriptor; size: "card" | "row" }) {
  const label = visualTileAccessibleName(tile);

  if (size === "row") {
    return (
      <Link
        href={tile.siteHref}
        aria-label={label}
        className="relative block size-full"
      >
        <RingPolygon tile={tile} />
        <span
          aria-hidden="true"
          className="absolute right-0 bottom-0 rounded-tl border border-b-0 border-line bg-surface px-1 text-[9px] font-semibold text-ink-2"
        >
          도식
        </span>
        <span className="sr-only">사진이 아닌 범위 도식입니다.</span>
      </Link>
    );
  }

  return (
    <Link
      href={tile.siteHref}
      aria-label={label}
      className="block size-full"
    >
      <figure className="relative flex size-full flex-col bg-sunk">
        {/* 도식은 카드 안에 남아야 한다 — 캡션이 카드 밖으로 새면 현장
            이름·상태·다음 행동이 화면 아래로 밀려난다. 캡션이 두꺼워지면
            도식 영역이 그만큼 줄어들도록 flex로 나눈다. */}
        <span className="relative min-h-0 flex-1">
          <RingPolygon tile={tile} />
        </span>
        <figcaption className="shrink-0 border-t border-line bg-surface px-4 py-2">
          <span className="block text-[12px] font-semibold break-keep">
            범위 도식 · 사진 아님
          </span>
          <span className="num mt-0.5 block min-w-0 text-[10.5px] break-keep text-ink-2">
            {visualTileCountLine(tile)}
            <span className="mt-px block min-w-0">{visualTileFactLine(tile)}</span>
          </span>
        </figcaption>
      </figure>
    </Link>
  );
}
