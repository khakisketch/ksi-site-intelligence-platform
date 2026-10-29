"use client";

import L from "leaflet";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Polygon, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { AnalysisCoverageWire, CoverageGridReference } from "@/lib/analysis-coverage";
import { coverageMapShapes, type CoverageMapShape } from "@/lib/geo/analysis-coverage-geometry";

function Fit({ shapes }: { shapes: CoverageMapShape[] }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(L.latLngBounds(shapes.flatMap((shape) => shape.positions)), { padding: [32,32], maxZoom: 26 });
  }, [map, shapes]);
  return null;
}

function Background() {
  const [boundaryOnly, setBoundaryOnly] = useState(false);
  useMapEvents({ zoomend: (event) => setBoundaryOnly(event.target.getZoom() > 19) });
  return boundaryOnly
    ? <div className="pointer-events-none absolute bottom-7 left-3 z-[400] max-w-64 rounded border border-line bg-surface px-3 py-2 text-xs leading-5 text-ink-2">셀 확대 보기 · 배경 지도의 해상도를 넘어 배경을 숨겼습니다.</div>
    : <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={19}
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />;
}

export function AnalysisCoverageMapInner({ witness, reference }: { witness: AnalysisCoverageWire; reference: CoverageGridReference }) {
  const result = useMemo(() => coverageMapShapes(witness, reference), [witness, reference]);
  if (!result.ok) return <p className="text-sm leading-6 text-high-ink">{result.reason}</p>;
  if (result.shapes.some((shape) => shape.positions.some(([lat]) => Math.abs(lat) > 85.05112878))) {
    return <p className="text-sm leading-6 text-high-ink">이 위치는 배경 지도 표시 범위를 벗어납니다. 계산 격자 보기는 유지됩니다.</p>;
  }
  return <div className="h-80 overflow-hidden rounded border border-line">
    <MapContainer center={result.shapes[0]!.positions[0]} zoom={16} maxZoom={26} style={{height:"100%",width:"100%"}}>
      <Background />
      <Fit shapes={result.shapes} />
      {result.shapes.map((shape, index) => <Polygon key={index} positions={shape.positions} pathOptions={{
        color: shape.state === "COMMON_VALID" ? "#134676" : shape.state === "UNAVAILABLE" ? "#7a4804" : "#8a1c16",
        weight: 1.5, fillOpacity: 0.55, dashArray: shape.state === "UNAVAILABLE" ? "4 3" : undefined,
      }}><Tooltip>{shape.state === "COMMON_VALID" ? "두 관측 유효" : shape.state === "UNAVAILABLE" ? "자료 없음 · 0이 아님" : "마스크 제외"} · 셀 경계 표시</Tooltip></Polygon>)}
    </MapContainer>
  </div>;
}
