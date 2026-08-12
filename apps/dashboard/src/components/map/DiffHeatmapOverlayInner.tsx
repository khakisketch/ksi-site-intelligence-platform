"use client";

import type * as L from "leaflet";
import GeoRasterLayer from "georaster-layer-for-leaflet";
import { useEffect } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import { registerKoreaProjections, proj4 } from "@/lib/geo/proj4-defs";
import { DIFF_CELL_COLOR, classifyDiffCell, diffIntensity } from "@/lib/design-conformance";

registerKoreaProjections();

type DiffLoadState =
  | { phase: "loading" }
  | { phase: "unavailable"; detail: string }
  | { phase: "ready"; maxAbsM: number };

type GeoRasterLayerInstance = L.Layer & {
  getBounds: () => L.LatLngBounds;
};

/**
 * 격자 전체를 훑어 **집계에 실제로 들어간 값**의 최대 절대값을 찾는다.
 *
 * 발산형 팔레트의 세기를 나누는 기준이다. 문턱 미만 값까지 포함해 최대를 잡으면
 * 지도가 "거의 다 됐다"처럼 흐려지고, NaN(모름)을 0 으로 세면 아예 틀린다.
 * 값이 하나도 없으면(전부 모름이거나 전부 문턱 미만) 0 을 돌려주고, 그때는
 * 세기를 나누지 않는다(`diffIntensity` 가 최댓값으로 고정한다).
 */
function maxAggregatedAbs(values: number[][][] | undefined, thresholdM: number): number {
  if (!values || values.length === 0) return 0;
  let max = 0;
  for (const row of values[0]) {
    for (const value of row) {
      if (!Number.isFinite(value)) continue;
      const magnitude = Math.abs(value);
      if (magnitude >= thresholdM && magnitude > max) max = magnitude;
    }
  }
  return max;
}

/**
 * 저장된 차분 래스터를 받아 3상태로 칠한다.
 *
 * 값은 `설계 표고 − 현재 표고` 다(계약 `DiffRasterRef`): 양수 = 쌓아야 함,
 * 음수 = 깎아야 함. 브라우저가 원본 두 장을 다시 차분하지 않는다 — 그러면 지도와
 * 표가 서로 다른 두 진실을 갖게 되고 그 어긋남은 어느 화면에서도 보이지 않는다.
 */
function DiffRasterLayer({
  missionId,
  designConformanceId,
  thresholdM,
  onState,
}: {
  missionId: string;
  designConformanceId: string;
  thresholdM: number;
  onState: (state: DiffLoadState) => void;
}) {
  const map = useMap();

  useEffect(() => {
    let cancelled = false;
    let layer: GeoRasterLayerInstance | null = null;

    async function load() {
      try {
        // presigned URL 은 수명이 분 단위다 — 마운트 시점에 직접 받는다.
        const urlResponse = await fetch(
          `/api/missions/${encodeURIComponent(missionId)}/design-conformance/${encodeURIComponent(designConformanceId)}/diff-raster`,
        );
        if (!urlResponse.ok) {
          throw new Error(`열람 URL 발급 실패: HTTP ${urlResponse.status}`);
        }
        const urlBody = (await urlResponse.json()) as { downloadUrl?: string };
        if (!urlBody.downloadUrl) throw new Error("열람 URL 을 받지 못했습니다");
        if (cancelled) return;

        const response = await fetch(urlBody.downloadUrl);
        if (!response.ok) throw new Error(`차분 자료 다운로드 실패: HTTP ${response.status}`);
        const arrayBuffer = await response.arrayBuffer();
        if (cancelled) return;

        const parseGeoraster = (await import("georaster")).default;
        const georaster = await parseGeoraster(arrayBuffer);
        if (cancelled) return;

        const maxAbsM = maxAggregatedAbs(georaster.values, thresholdM);

        layer = new GeoRasterLayer({
          georaster,
          resolution: 256,
          proj4,
          opacity: 0.75,
          pixelValuesToColorFn: (values: number[]) => {
            const value = values[0];
            const cell = classifyDiffCell(
              value === undefined || value === null ? null : value,
              thresholdM,
            );
            const color = DIFF_CELL_COLOR[cell];
            if (cell === "unknown" || cell === "below-threshold") return color;
            // 같은 색의 세기로 크기를 말한다 — 색상(파랑/주황)이 방향을,
            // 진하기가 양을 담당한다(색만으로 방향을 읽지 않아도 되게 범례에
            // 글자를 병기한다).
            const alpha = 0.35 + 0.65 * diffIntensity(value, maxAbsM);
            return `${color}${Math.round(alpha * 255)
              .toString(16)
              .padStart(2, "0")}`;
          },
        }) as unknown as GeoRasterLayerInstance;
        layer.addTo(map);
        const bounds = layer.getBounds();
        if (bounds.isValid()) map.fitBounds(bounds, { maxZoom: 20 });
        onState({ phase: "ready", maxAbsM });
      } catch (error) {
        if (cancelled) return;
        onState({
          phase: "unavailable",
          detail: error instanceof Error ? error.message : "알 수 없는 오류",
        });
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (layer) map.removeLayer(layer);
    };
  }, [map, missionId, designConformanceId, thresholdM, onState]);

  return null;
}

export function DiffHeatmapOverlayInner({
  missionId,
  designConformanceId,
  thresholdM,
  center,
  onState,
}: {
  missionId: string;
  designConformanceId: string;
  thresholdM: number;
  center: [number, number];
  onState: (state: DiffLoadState) => void;
}) {
  return (
    <MapContainer
      center={center}
      zoom={18}
      style={{ height: "100%", width: "100%" }}
      className="rounded-lg"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <DiffRasterLayer
        missionId={missionId}
        designConformanceId={designConformanceId}
        thresholdM={thresholdM}
        onState={onState}
      />
    </MapContainer>
  );
}

export type { DiffLoadState };
