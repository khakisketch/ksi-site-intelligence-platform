"use client";

import L from "leaflet";
import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import type { AoiVertex, ChangeRegion } from "@/lib/core-api/types";
import { DIFF_CELL_COLOR } from "@/lib/design-conformance";

// AoiPolygonMapInner 와 같은 이유로 클라이언트 전용(leaflet 이 window/document 직접 참조).

/** 현장 외곽 — 맥락으로만 보여준다(옅은 선, 클릭 불가). */
function SiteOutline({ vertices }: { vertices: AoiVertex[] }) {
  const map = useMap();
  useEffect(() => {
    if (vertices.length < 3) return;
    const layer = L.polygon(
      vertices.map((v) => [v.latDeg, v.lonDeg]),
      { color: "#8a8578", weight: 1, dashArray: "4 4", fill: false, interactive: false },
    );
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, vertices]);
  return null;
}

/**
 * 변화 영역 폴리곤들 — hull 계산이 성공한 영역만 그린다(``convexHullPolygonWgs84``
 * 가 있는 것만). 색은 순증감 부호를 따른다: 쌓아야 함(양수)=파랑, 깎아야
 * 함(음수)=주황 — `DiffHeatmapOverlay` 범례와 같은 팔레트(전역에서 색의 의미를
 * 하나로 유지한다).
 *
 * 두 effect 로 나눈 이유: 폴리곤을 다시 그리는 것(``regions`` 변경)과 선택
 * 상태만 바꾸는 것(``selectedRegionId`` 변경)을 분리해, 영역을 고를 때마다
 * 지도가 다시 맞춰지며 튀지 않게 한다.
 */
function RegionLayers({
  regions,
  selectedRegionId,
  onSelect,
}: {
  regions: ChangeRegion[];
  selectedRegionId: string | null;
  onSelect: (regionId: string) => void;
}) {
  const map = useMap();
  const layersRef = useRef<Map<string, L.Polygon>>(new Map());

  useEffect(() => {
    const group = L.featureGroup();
    const layers = new Map<string, L.Polygon>();
    for (const region of regions) {
      const hull = region.convexHullPolygonWgs84;
      if (!hull) continue;
      const ring = hull.coordinates[0];
      if (!ring || ring.length < 3) continue;
      const latlngs = ring.map(([lon, lat]) => [lat, lon] as [number, number]);
      const color = region.volume.netM3 >= 0 ? DIFF_CELL_COLOR.fill : DIFF_CELL_COLOR.cut;
      const layer = L.polygon(latlngs, { color, weight: 1.5, fillOpacity: 0.25 });
      layer.on("click", () => onSelect(region.regionId));
      layer.addTo(group);
      layers.set(region.regionId, layer);
    }
    group.addTo(map);
    layersRef.current = layers;
    if (group.getLayers().length > 0) {
      map.fitBounds(group.getBounds(), { maxZoom: 18, padding: [24, 24] });
    }
    return () => {
      map.removeLayer(group);
      layersRef.current = new Map();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- selectedRegionId 는 별도 effect가 스타일만 갱신(재적합 방지 위해 여기서 제외).
  }, [map, regions]);

  useEffect(() => {
    for (const [regionId, layer] of layersRef.current) {
      const selected = regionId === selectedRegionId;
      layer.setStyle({ weight: selected ? 3.5 : 1.5, fillOpacity: selected ? 0.5 : 0.25 });
      if (selected) layer.bringToFront();
    }
  }, [selectedRegionId]);

  return null;
}

export function ChangeRegionMapInner({
  siteAoi,
  regions,
  selectedRegionId,
  onSelectRegion,
  center = [37.5665, 126.978],
}: {
  siteAoi: AoiVertex[];
  regions: ChangeRegion[];
  selectedRegionId: string | null;
  onSelectRegion: (regionId: string) => void;
  center?: [number, number];
}) {
  return (
    <MapContainer center={center} zoom={16} style={{ height: "100%", width: "100%" }} className="rounded-lg">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <SiteOutline vertices={siteAoi} />
      <RegionLayers regions={regions} selectedRegionId={selectedRegionId} onSelect={onSelectRegion} />
    </MapContainer>
  );
}
