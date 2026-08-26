"use client";

import type * as L from "leaflet";
import { useEffect } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import { DIFF_CELL_COLOR, classifyDiffCell, diffIntensity } from "@/lib/design-conformance";
import {
  createDiffRasterOverlay,
  revokeRasterObjectUrl,
} from "@/lib/geo/geotiff-overlay";
import { usePrintMapResize } from "@/hooks/usePrintMapResize";

type DiffLoadState =
  | { phase: "loading" }
  | { phase: "unavailable"; detail: string }
  | { phase: "ready"; maxAbsM: number };

const HEX_COLOR = /^#([0-9a-f]{6})$/i;

function colorTuple(hex: string, alpha = 1): readonly [number, number, number, number] {
  const match = HEX_COLOR.exec(hex);
  if (!match) throw new Error(`지원하지 않는 차분 지도 색상: ${hex}`);
  const value = Number.parseInt(match[1], 16);
  return [
    (value >> 16) & 0xff,
    (value >> 8) & 0xff,
    value & 0xff,
    Math.round(Math.max(0, Math.min(1, alpha)) * 255),
  ];
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
  usePrintMapResize(map);

  useEffect(() => {
    let cancelled = false;
    let layer: L.ImageOverlay | null = null;
    let imageUrl: string | null = null;

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

        const overlay = await createDiffRasterOverlay(
          arrayBuffer,
          thresholdM,
          (value, maxAbsM) => {
            const cell = classifyDiffCell(value, thresholdM);
            if (cell === "unknown" || cell === "below-threshold") {
              return colorTuple(DIFF_CELL_COLOR[cell]);
            }
            // 같은 색의 세기로 크기를 말한다 — 색상(파랑/주황)이 방향을,
            // 진하기가 양을 담당한다(색만으로 방향을 읽지 않아도 되게 범례에
            // 글자를 병기한다).
            const alpha = 0.35 + 0.65 * diffIntensity(value ?? 0, maxAbsM);
            return colorTuple(DIFF_CELL_COLOR[cell], alpha);
          },
        );
        if (cancelled) {
          revokeRasterObjectUrl(overlay.imageUrl);
          return;
        }
        imageUrl = overlay.imageUrl;
        const leaflet = await import("leaflet");
        if (cancelled) {
          revokeRasterObjectUrl(imageUrl);
          imageUrl = null;
          return;
        }
        layer = leaflet.imageOverlay(imageUrl, overlay.bounds, {
          opacity: 0.75,
          interactive: false,
        });
        layer.addTo(map);
        const bounds = layer.getBounds();
        if (bounds.isValid()) map.fitBounds(bounds, { maxZoom: 20 });
        onState({ phase: "ready", maxAbsM: overlay.maxAbsM });
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
      revokeRasterObjectUrl(imageUrl);
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
