"use client";

import L from "leaflet";
import { useEffect } from "react";
import { MapContainer, Polygon, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { SurveyRegionShape } from "@/lib/geo/survey-region-geometry";

function Fit({ shapes }: { shapes: SurveyRegionShape[] }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(L.latLngBounds(shapes.flatMap((shape) => shape.positions)), { padding: [32, 32] });
  }, [map, shapes]);
  return null;
}

export function SurveyRegionMapInner(props: {
  shapes: SurveyRegionShape[];
  selectedId: string | null;
  onSelect: (regionId: string | null) => void;
}) {
  const first = props.shapes[0];
  if (!first) return null;
  return (
    <div className="h-80 overflow-hidden rounded border border-line">
      <MapContainer center={first.positions[0]} zoom={16} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxNativeZoom={19}
          maxZoom={19}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        />
        <Fit shapes={props.shapes} />
        {props.shapes.map((shape) => {
          const selected = shape.regionId === props.selectedId;
          return (
            <Polygon
              key={shape.regionId}
              positions={shape.positions}
              pathOptions={{
                color: selected ? "#8a1c16" : "#134676",
                weight: selected ? 3 : 1.5,
                fillOpacity: selected ? 0.65 : 0.45,
              }}
              eventHandlers={{ click: () => props.onSelect(shape.regionId) }}
            >
              <Tooltip>{`후보 ${shape.regionId}`}</Tooltip>
            </Polygon>
          );
        })}
      </MapContainer>
    </div>
  );
}
