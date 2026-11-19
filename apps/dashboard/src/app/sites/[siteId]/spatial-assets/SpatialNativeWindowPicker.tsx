"use client";

import type { MouseEvent } from "react";

import type { InspectedRasterGrid, PixelWindowSelection } from "@/lib/spatial-data-request";

/** Convert a point in the inspected grid to a centered, edge-clamped window origin. */
export function pixelWindowOriginAtPoint(
  gridWidth: number,
  gridHeight: number,
  windowWidth: number,
  windowHeight: number,
  xRatio: number,
  yRatio: number,
): { col: number; row: number } | null {
  if (![gridWidth, gridHeight, windowWidth, windowHeight].every(Number.isInteger)
    || gridWidth <= 0 || gridHeight <= 0 || windowWidth <= 0 || windowHeight <= 0
    || windowWidth > gridWidth || windowHeight > gridHeight
    || !Number.isFinite(xRatio) || !Number.isFinite(yRatio)) return null;

  const x = Math.min(1, Math.max(0, xRatio));
  const y = Math.min(1, Math.max(0, yRatio));
  return {
    col: Math.min(gridWidth - windowWidth, Math.max(0, Math.round(x * gridWidth - windowWidth / 2))),
    row: Math.min(gridHeight - windowHeight, Math.max(0, Math.round(y * gridHeight - windowHeight / 2))),
  };
}

export function SpatialNativeWindowPicker({
  raster,
  selection,
  disabled,
  onPick,
}: {
  raster: InspectedRasterGrid;
  selection: PixelWindowSelection;
  disabled: boolean;
  onPick: (origin: { col: number; row: number }) => void;
}) {
  const pixelWidth = raster.transform[0];
  const pixelHeight = raster.transform[4];
  const coordinateWidth = pixelWidth * raster.width;
  const coordinateHeight = -pixelHeight * raster.height;
  const aspect = coordinateWidth / coordinateHeight;
  if (!Number.isFinite(aspect) || aspect <= 0) return null;

  const maxWidth = Math.min(480, 230 * aspect);
  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    // Keyboard activation has no pointer location; center the window in that case.
    const keyboardActivation = event.detail === 0;
    const xRatio = keyboardActivation ? 0.5 : (event.clientX - bounds.left) / bounds.width;
    const yRatio = keyboardActivation ? 0.5 : (event.clientY - bounds.top) / bounds.height;
    const origin = pixelWindowOriginAtPoint(
      raster.width,
      raster.height,
      selection.width,
      selection.height,
      xRatio,
      yRatio,
    );
    if (origin) onPick(origin);
  };

  const columnEnd = selection.col + selection.width - 1;
  const rowEnd = selection.row + selection.height - 1;
  return (
    <div className="min-w-0">
      <p className="text-caption font-semibold text-ink-1">파일 안에서 위치 선택</p>
      <button
        type="button"
        className="relative mx-auto mt-2 block w-full overflow-hidden rounded border border-line-strong bg-sunk text-ink-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-1 disabled:cursor-not-allowed disabled:opacity-70"
        style={{ aspectRatio: `${coordinateWidth} / ${coordinateHeight}`, maxWidth: `${maxWidth}px` }}
        aria-label={`검사한 파일 격자에서 현재 요청 창을 옮깁니다. 파일 ${raster.width} × ${raster.height} 픽셀, 선택 열 ${selection.col}–${columnEnd}, 행 ${selection.row}–${rowEnd}. 키보드로 활성화하면 가운데로 옮깁니다.`}
        disabled={disabled}
        onClick={handleClick}
      >
        <svg
          aria-hidden="true"
          className="absolute inset-0 h-full w-full"
          viewBox={`0 0 ${raster.width} ${raster.height}`}
          preserveAspectRatio="none"
        >
          <rect width={raster.width} height={raster.height} fill="currentColor" opacity="0.035" />
          {Array.from({ length: 7 }, (_, index) => {
            const fraction = (index + 1) / 8;
            return (
              <g key={index} opacity="0.28">
                <line x1={raster.width * fraction} y1="0" x2={raster.width * fraction} y2={raster.height} stroke="currentColor" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                <line x1="0" y1={raster.height * fraction} x2={raster.width} y2={raster.height * fraction} stroke="currentColor" strokeWidth="1" vectorEffect="non-scaling-stroke" />
              </g>
            );
          })}
          <rect
            x={selection.col}
            y={selection.row}
            width={selection.width}
            height={selection.height}
            fill="currentColor"
            fillOpacity="0.24"
            stroke="currentColor"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
          <rect x="0" y="0" width={raster.width} height={raster.height} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        </svg>
      </button>
      <p className="mt-2 text-caption text-ink-2" aria-live="polite">
        현재 창 · 열 {selection.col}–{columnEnd}, 행 {selection.row}–{rowEnd}
      </p>
    </div>
  );
}
