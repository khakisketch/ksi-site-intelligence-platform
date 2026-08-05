"use client";

import L from "leaflet";
import "leaflet-draw";
import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import type { AoiVertex } from "@/lib/core-api/types";

// PRD §7.3 "지도에서 외곽 선택" 실체화 — 단순 폴리곤(3~256 꼭짓점, POST /v1/missions/plans
// aoi.vertices 계약)만 지원한다. leaflet-draw 는 side-effect import 로 전역 L 에 컨트롤을
// 붙이므로 클라이언트 전용(SSR 비활성, AoiPolygonMap.tsx 의 dynamic import 가 담당).

const _MAX_AOI_VERTICES = 256;

function toVertices(layer: L.Polygon): AoiVertex[] {
  const latlngs = layer.getLatLngs()[0] as L.LatLng[];
  return latlngs.map((p) => ({ latDeg: p.lat, lonDeg: p.lng }));
}

/** 편집 컨트롤 없이 폴리곤만 그린다 — 현장 상세 화면처럼 "보여주기만" 하는 자리용. */
function ReadOnlyPolygon({ value }: { value: AoiVertex[] }) {
  const map = useMap();

  useEffect(() => {
    if (value.length < 3) return;
    const polygon = L.polygon(value.map((v) => [v.latDeg, v.lonDeg]));
    polygon.addTo(map);
    map.fitBounds(polygon.getBounds(), { maxZoom: 18 });
    return () => {
      map.removeLayer(polygon);
    };
  }, [map, value]);

  return null;
}

function DrawControl({
  value,
  onChange,
}: {
  value: AoiVertex[];
  onChange: (vertices: AoiVertex[]) => void;
}) {
  const map = useMap();
  const groupRef = useRef<L.FeatureGroup>(new L.FeatureGroup());

  useEffect(() => {
    const group = groupRef.current;
    map.addLayer(group);

    if (value.length >= 3) {
      const existing = L.polygon(value.map((v) => [v.latDeg, v.lonDeg]));
      group.addLayer(existing);
      map.fitBounds(existing.getBounds(), { maxZoom: 18 });
    }

    const control = new L.Control.Draw({
      draw: {
        polygon: {
          allowIntersection: false,
          showArea: true,
          drawError: { message: "AOI는 자기교차 없는 단순 폴리곤이어야 합니다." },
        },
        // AOI 는 폴리곤 하나만 필요 — 나머지 도형 도구는 노출하지 않는다(스코프 축소).
        polyline: false,
        rectangle: false,
        circle: false,
        circlemarker: false,
        marker: false,
      },
      edit: { featureGroup: group, remove: true },
    });
    map.addControl(control);

    const emit = () => {
      const layers = group.getLayers() as L.Polygon[];
      const last = layers[layers.length - 1];
      if (!last) {
        onChange([]);
        return;
      }
      const vertices = toVertices(last);
      onChange(vertices.slice(0, _MAX_AOI_VERTICES));
    };

    const onCreated = (e: L.LeafletEvent) => {
      group.clearLayers(); // AOI 폴리곤은 하나만 유지 — 새로 그리면 이전 것을 대체.
      group.addLayer((e as L.DrawEvents.Created).layer);
      emit();
    };
    const onEdited = () => emit();
    const onDeleted = () => emit();

    map.on(L.Draw.Event.CREATED, onCreated);
    map.on(L.Draw.Event.EDITED, onEdited);
    map.on(L.Draw.Event.DELETED, onDeleted);

    return () => {
      map.off(L.Draw.Event.CREATED, onCreated);
      map.off(L.Draw.Event.EDITED, onEdited);
      map.off(L.Draw.Event.DELETED, onDeleted);
      map.removeControl(control);
      map.removeLayer(group);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 최초 마운트에만 컨트롤 부착, value 는 초기값으로만 사용
  }, [map]);

  return null;
}

export function AoiPolygonMapInner({
  value,
  onChange,
  center = [37.5665, 126.978], // 서울 — 현장 등록 전 기본 시야일 뿐 데이터 아님.
  readOnly = false,
}: {
  value: AoiVertex[];
  /** readOnly 가 아니면 필수 — 서버 컴포넌트(현장 상세)에서 readOnly 로 쓸 땐 함수를 넘기지 않는다. */
  onChange?: (vertices: AoiVertex[]) => void;
  center?: [number, number];
  /** true 면 편집 컨트롤 없이 폴리곤만 표시한다(현장 상세처럼 보여주기 전용 자리). */
  readOnly?: boolean;
}) {
  return (
    <MapContainer
      center={center}
      zoom={16}
      style={{ height: "100%", width: "100%" }}
      className="rounded-lg"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {readOnly ? (
        <ReadOnlyPolygon value={value} />
      ) : (
        <DrawControl value={value} onChange={onChange as (vertices: AoiVertex[]) => void} />
      )}
    </MapContainer>
  );
}
