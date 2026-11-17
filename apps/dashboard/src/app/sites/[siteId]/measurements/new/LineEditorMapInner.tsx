"use client";

import L from "leaflet";
import { useEffect } from "react";
import { MapContainer, Marker, Polygon, Polyline, TileLayer, useMap, useMapEvents } from "react-leaflet";

import type { LineVertex } from "@/lib/measurement-line";
import type { LineEditorMapProps } from "./LineEditorMap";

// 점은 기본 마커 이미지 없이 작은 원으로 그린다(정적 이미지 경로에 기대지 않는다).
const pointIcon = (index: number, last: boolean) => L.divIcon({
  className: "",
  html: `<span style="display:flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:9999px;background:${last ? "#17633b" : "#ffffff"};color:${last ? "#ffffff" : "#17633b"};border:2px solid #17633b;font:600 11px system-ui;box-shadow:0 1px 3px rgba(0,0,0,.35)">${index + 1}</span>`,
  iconSize: [22, 22],
  iconAnchor: [11, 11],
});

const toLatLng = ([lon, lat]: LineVertex): [number, number] => [lat, lon];

function Fit({ ring, vertices }: { ring: LineVertex[] | null; vertices: LineVertex[] }) {
  const map = useMap();
  // 처음 한 번만 구역(없으면 선)에 맞춘다. 그리는 중에 지도가 움직이면 누르기 어렵다.
  useEffect(() => {
    // 동적으로 불러온 직후에는 컨테이너 크기가 아직 0일 수 있다. 크기를 다시 읽은 뒤 맞춘다.
    map.invalidateSize();
    const points = (ring && ring.length > 0 ? ring : vertices).map(toLatLng);
    if (points.length > 0) map.fitBounds(L.latLngBounds(points), { padding: [32, 32], maxZoom: 19 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);
  return null;
}

function Clicks({ disabled, onAdd }: { disabled: boolean; onAdd: (vertex: LineVertex) => void }) {
  useMapEvents({
    click(event) {
      if (!disabled) onAdd([event.latlng.lng, event.latlng.lat]);
    },
  });
  return null;
}

export function LineEditorMapInner({ vertices, ring, disabled, onAdd, onMove }: LineEditorMapProps) {
  const center: [number, number] = ring && ring.length > 0 ? toLatLng(ring[0]!) : vertices.length > 0 ? toLatLng(vertices[0]!) : [37.5, 127];
  return (
    <MapContainer center={center} zoom={17} maxZoom={19} style={{ height: "100%", width: "100%", cursor: disabled ? "default" : "crosshair" }} doubleClickZoom={false}>
      <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={19}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
      <Fit ring={ring} vertices={vertices} />
      <Clicks disabled={disabled} onAdd={onAdd} />
      {ring && ring.length >= 3 && <Polygon positions={ring.map(toLatLng)} interactive={false} pathOptions={{ color: "#46536b", weight: 2, dashArray: "6 6", fillOpacity: 0.08 }} />}
      {vertices.length >= 2 && <Polyline positions={vertices.map(toLatLng)} interactive={false} pathOptions={{ color: "#17633b", weight: 4 }} />}
      {vertices.map((vertex, index) => (
        <Marker
          key={`${index}`}
          position={toLatLng(vertex)}
          icon={pointIcon(index, index === vertices.length - 1)}
          draggable={!disabled}
          eventHandlers={{
            dragend(event) {
              const { lat, lng } = (event.target as L.Marker).getLatLng();
              onMove(index, [lng, lat]);
            },
          }}
        />
      ))}
    </MapContainer>
  );
}
