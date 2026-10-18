"use client";

import type * as L from "leaflet";
import { useEffect } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import {
  fetchVerifiedSanitizedDisplay,
  isExternalSanitizedDisplayCapability,
} from "@/lib/external-sanitized-display";
import { createOrthophotoOverlay, revokeRasterObjectUrl } from "@/lib/geo/geotiff-overlay";
import { usePrintMapResize } from "@/hooks/usePrintMapResize";

export type ExternalSanitizedOrthophotoLoadState =
  | { phase: "loading" }
  | { phase: "ready" }
  | { phase: "unavailable"; detail: string };

function SanitizedRasterLayer({
  workOrderId,
  submissionRef,
  revision,
  sanitizedDisplayRef,
  receiptDigest,
  onState,
}: {
  workOrderId: string;
  submissionRef: string;
  revision: number;
  sanitizedDisplayRef: string;
  receiptDigest: string;
  onState: (state: ExternalSanitizedOrthophotoLoadState) => void;
}) {
  const map = useMap();
  usePrintMapResize(map);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let layer: L.ImageOverlay | null = null;
    let imageUrl: string | null = null;

    async function load() {
      try {
        const capabilityResponse = await fetch(
          `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(submissionRef)}/revisions/${revision}/display-artifacts/${encodeURIComponent(sanitizedDisplayRef)}/download`,
          { cache: "no-store", signal: controller.signal },
        );
        if (!capabilityResponse.ok) throw new Error(`표시용 정사영상 권한 발급 실패: HTTP ${capabilityResponse.status}`);
        const capability: unknown = await capabilityResponse.json();
        if (!isExternalSanitizedDisplayCapability(capability) || capability.sanitizedDisplayRef !== sanitizedDisplayRef || capability.receiptDigest !== receiptDigest) {
          throw new Error("현재 검사 영수증과 다른 표시용 정사영상 권한을 거부했습니다.");
        }
        const arrayBuffer = await fetchVerifiedSanitizedDisplay(capability, controller.signal);
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
        layer = leaflet.imageOverlay(imageUrl, overlay.bounds, { interactive: false });
        layer.addTo(map);
        const bounds = layer.getBounds();
        if (bounds.isValid()) map.fitBounds(bounds, { maxZoom: 20 });
        onState({ phase: "ready" });
      } catch (error) {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) return;
        onState({ phase: "unavailable", detail: error instanceof Error ? error.message : "알 수 없는 오류" });
      }
    }

    void load();
    return () => {
      cancelled = true;
      controller.abort();
      if (layer) map.removeLayer(layer);
      revokeRasterObjectUrl(imageUrl);
    };
  }, [map, workOrderId, submissionRef, revision, sanitizedDisplayRef, receiptDigest, onState]);

  return null;
}

export function ExternalSanitizedOrthophotoInner(props: Omit<Parameters<typeof SanitizedRasterLayer>[0], "onState"> & { onState: (state: ExternalSanitizedOrthophotoLoadState) => void }) {
  return (
    <MapContainer center={[37.5665, 126.978]} zoom={18} style={{ height: "100%", width: "100%" }} className="rounded-lg">
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <SanitizedRasterLayer {...props} />
    </MapContainer>
  );
}
