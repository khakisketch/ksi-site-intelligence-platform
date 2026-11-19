"use client";

import L from "leaflet";
import { useEffect, useRef } from "react";
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

function Fit({ extent }: { extent: LineVertex[] }) {
  const map = useMap();
  const initialExtent = useRef(extent);
  useEffect(() => {
    map.invalidateSize();
    const points = initialExtent.current.map(toLatLng);
    if (points.length > 0) map.fitBounds(L.latLngBounds(points), { padding: [32, 32], maxZoom: 19 });
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

export function LineEditorMapInner({ vertices, ring, sourceRing, focusRing, disabled, onAdd, onMove }: LineEditorMapProps) {
  const initialExtent = vertices.length > 1 ? vertices : focusRing ?? ring ?? vertices;
  const center: [number, number] = initialExtent.length > 0 ? toLatLng(initialExtent[0]!) : [37.5, 127];
  return (
    <div className="relative h-full w-full">
      <MapContainer center={center} zoom={17} maxZoom={19} style={{ height: "100%", width: "100%", cursor: disabled ? "default" : "crosshair" }} doubleClickZoom={false}>
        <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={19}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
        <Fit extent={initialExtent} />
        <Clicks disabled={disabled} onAdd={onAdd} />
        {sourceRing && sourceRing.length >= 3 && <Polygon positions={sourceRing.map(toLatLng)} interactive={false} pathOptions={{ color: "#d97706", weight: 3, fillColor: "#f59e0b", fillOpacity: 0.16 }} />}
        {ring && ring.length >= 3 && <Polygon positions={ring.map(toLatLng)} interactive={false} pathOptions={{ color: "#46536b", weight: 2, dashArray: "6 6", fillOpacity: 0.04 }} />}
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
      {(ring || sourceRing) && (
        <div aria-label="지도 범례" className="pointer-events-none absolute right-3 top-3 z-[500] rounded-lg border border-line bg-surface/95 px-3 py-2 text-micro leading-5 text-ink-2 shadow-sm">
          {ring && <p><span aria-hidden="true" className="mr-2 inline-block w-5 border-t-2 border-dashed border-slate-600 align-middle" />작업구역 경계</p>}
          {sourceRing && <p><span aria-hidden="true" className="mr-2 inline-block w-5 border-t-2 border-amber-600 align-middle" />자료 격자 경계</p>}
        </div>
      )}
    </div>
  );
}
