"use client";

import type * as L from "leaflet";
import { useEffect } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import {
  createOrthophotoOverlay,
  revokeRasterObjectUrl,
} from "@/lib/geo/geotiff-overlay";
import { usePrintMapResize } from "@/hooks/usePrintMapResize";

type LoadState =
  | { phase: "loading" }
  | { phase: "unavailable"; detail: string }
  | { phase: "ready" };

/**
 * GeoTIFF 정사영상을 실제로 파싱해 Leaflet ImageOverlay 위에 얹는다. 이 파일이 하는 일은
 * "산출물이 실제로 저장·재다운로드된다"(Task C) 다음의 마지막 겹이다 — 바이트가
 * 있어도 화면에 안 그려지면 사람이 볼 수 있는 것은 여전히 없다.
 *
 * presigned URL 은 TTL 이 분 단위다(``DEFAULT_VIEW_TTL``) — 서버 컴포넌트가
 * 렌더 시점에 미리 발급해 prop 으로 넘기면 클라이언트가 실제로 쓸 때 이미
 * 만료될 수 있다(evidence 뷰어와 같은 이유). 그래서 이 컴포넌트가 직접,
 * 마운트되는 시점에 프록시 라우트를 호출해 URL 을 받는다.
 */
function RasterLayer({
  jobId,
  artifactId,
  onState,
}: {
  jobId: string;
  artifactId: string;
  onState: (state: LoadState) => void;
}) {
  const map = useMap();
  usePrintMapResize(map);

  useEffect(() => {
    let cancelled = false;
    let layer: L.ImageOverlay | null = null;
    let imageUrl: string | null = null;

    async function load() {
      try {
        const urlResponse = await fetch(
          `/api/processing-jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactId)}/download`,
        );
        if (!urlResponse.ok) {
          throw new Error(`다운로드 URL 발급 실패: HTTP ${urlResponse.status}`);
        }
        const urlBody = (await urlResponse.json()) as { verdict: string; downloadUrl: string | null };
        if (urlBody.verdict !== "ARTIFACT_READY" || !urlBody.downloadUrl) {
          throw new Error(`산출물을 아직 받을 수 없습니다(${urlBody.verdict})`);
        }
        if (cancelled) return;

        const response = await fetch(urlBody.downloadUrl);
        if (!response.ok) {
          throw new Error(`정사영상 다운로드 실패: HTTP ${response.status}`);
        }
        const arrayBuffer = await response.arrayBuffer();
        if (cancelled) return;

        const overlay = await createOrthophotoOverlay(arrayBuffer);
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
          interactive: false,
        });
        layer.addTo(map);
        const bounds = layer.getBounds();
        if (bounds.isValid()) {
          map.fitBounds(bounds, { maxZoom: 20 });
        }
        onState({ phase: "ready" });
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
  }, [map, jobId, artifactId, onState]);

  return null;
}

export function OrthophotoOverlayInner({
  jobId,
  artifactId,
  center,
  onState,
}: {
  jobId: string;
  artifactId: string;
  center: [number, number];
  onState: (state: LoadState) => void;
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
      <RasterLayer jobId={jobId} artifactId={artifactId} onState={onState} />
    </MapContainer>
  );
}

export type { LoadState };
