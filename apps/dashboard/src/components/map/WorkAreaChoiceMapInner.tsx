"use client";

import L from "leaflet";
import { useEffect, useState } from "react";
import { MapContainer, Polygon, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { SupportedWorkAreaShape } from "@/lib/geo/display-geometry";

function FitAreas({ shapes }: { shapes: SupportedWorkAreaShape[] }) {
  const map = useMap();
  useEffect(() => {
    const positions = shapes.flatMap((shape) => shape.positions);
    if (positions.length) map.fitBounds(L.latLngBounds(positions), { padding: [32, 32], maxZoom: 26 });
  }, [map, shapes]);
  return null;
}

function ReadableBackground() {
  const [boundaryOnly, setBoundaryOnly] = useState(false);
  useMapEvents({ zoomend: (event) => setBoundaryOnly(event.target.getZoom() > 19) });
  return boundaryOnly
    ? <div className="pointer-events-none absolute bottom-7 left-3 z-[400] max-w-64 rounded border border-line bg-surface px-3 py-2 text-xs leading-5 text-ink-2">경계 확대 보기 · 배경 지도의 해상도를 넘어 배경을 숨겼습니다.</div>
    : <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={19}
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />;
}

export function WorkAreaChoiceMapInner({ shapes, selectedId, onSelect, disabled }: {
  shapes: SupportedWorkAreaShape[]; selectedId: string; onSelect: (id: string) => void; disabled: boolean;
}) {
  if (!shapes.length) return <p className="p-5 text-sm text-ink-2">지도에 표시할 수 있는 구역이 없습니다. 등록된 이름으로 선택할 수 있으며, 좌표를 추정해 그리지 않습니다.</p>;
  return <MapContainer center={shapes[0].positions[0]} zoom={16} maxZoom={26} style={{ height: "100%", width: "100%" }}>
    <ReadableBackground />
    <FitAreas shapes={shapes} />
    {shapes.map((shape) => <Polygon key={shape.id} positions={shape.positions}
      pathOptions={{ color: shape.id === selectedId ? "#17633b" : "#46536b", weight: shape.id === selectedId ? 4 : 2,
        fillOpacity: shape.id === selectedId ? 0.32 : 0.18 }}
      eventHandlers={{ click: () => { if (!disabled) onSelect(shape.id); } }}>
      <Tooltip key={shape.id === selectedId ? "selected" : "candidate"} permanent={shape.id === selectedId}>
        {shape.name}{shape.id === selectedId ? " · 선택됨" : ""}
      </Tooltip>
    </Polygon>)}
  </MapContainer>;
}
