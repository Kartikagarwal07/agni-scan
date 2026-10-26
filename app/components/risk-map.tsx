"use client";

import * as maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { GridFeature, RiskGrid } from "../lib/api";

const SOURCE_ID = "risk-grid";
const FILL_LAYER_ID = "risk-grid-fill";
const LINE_LAYER_ID = "risk-grid-outline";

type RiskMapProps = {
  data: RiskGrid;
  selectedCellId: string | null;
  onSelectCell: (cellId: string) => void;
};

function fitGrid(map: maplibregl.Map, features: GridFeature[]) {
  const bounds = new maplibregl.LngLatBounds();
  for (const feature of features) {
    for (const ring of feature.geometry.coordinates) {
      for (const [longitude, latitude] of ring) bounds.extend([longitude, latitude]);
    }
  }
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 62, maxZoom: 10, duration: 0 });
}

export default function RiskMap({ data, selectedCellId, onSelectCell }: RiskMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const dataRef = useRef(data);
  const selectedCellIdRef = useRef(selectedCellId);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "background", type: "background", paint: { "background-color": "#10191e" } }],
      },
      attributionControl: false,
      cooperativeGestures: true,
    });
    mapRef.current = map;
    popupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      map.addSource(SOURCE_ID, { type: "geojson", data: dataRef.current });
      map.addLayer({
        id: FILL_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        paint: {
          "fill-color": [
            "case",
            ["==", ["get", "cell_id"], selectedCellIdRef.current ?? ""],
            "#f0bc87",
            [
              "match",
              ["get", "risk_level"],
              "high", "#c65d50",
              "medium", "#d3944e",
              "low", "#4a9a77",
              "#748492",
            ],
          ],
          "fill-opacity": [
            "case",
            ["==", ["get", "cell_id"], selectedCellIdRef.current ?? ""],
            0.78,
            0.48,
          ],
        },
      });
      map.addLayer({
        id: LINE_LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        paint: {
          "line-color": [
            "case",
            ["==", ["get", "cell_id"], selectedCellIdRef.current ?? ""],
            "#ffe1bd",
            "#a6b3b4",
          ],
          "line-width": [
            "case",
            ["==", ["get", "cell_id"], selectedCellIdRef.current ?? ""],
            2.5,
            0.8,
          ],
        },
      });
      fitGrid(map, dataRef.current.features);

      map.on("mousemove", FILL_LAYER_ID, (event) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = event.features?.[0];
        if (!feature || typeof feature.properties?.cell_id !== "string") return;
        const properties = feature.properties;
        const risk = properties.risk_score === null ? "score unavailable" : `score ${properties.risk_score}`;
        popupRef.current
          ?.setLngLat(event.lngLat)
          .setText(`${properties.cell_id} · ${properties.district} · ${properties.risk_level} (${risk})`)
          .addTo(map);
      });
      map.on("mouseleave", FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = "";
        popupRef.current?.remove();
      });
      map.on("click", FILL_LAYER_ID, (event) => {
        const cellId = event.features?.[0]?.properties?.cell_id;
        if (typeof cellId === "string") onSelectCell(cellId);
      });
    });

    map.on("error", (event) => {
      setMapError(event.error.message || "MapLibre could not render the grid.");
    });

    return () => {
      popupRef.current?.remove();
      popupRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, [onSelectCell]);

  useEffect(() => {
    dataRef.current = data;
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    const source = map.getSource(SOURCE_ID);
    if (!(source instanceof maplibregl.GeoJSONSource)) return;
    source.setData(data);
    fitGrid(map, data.features);
  }, [data]);

  useEffect(() => {
    selectedCellIdRef.current = selectedCellId;
    const map = mapRef.current;
    if (!map?.isStyleLoaded() || !map.getLayer(FILL_LAYER_ID) || !map.getLayer(LINE_LAYER_ID)) return;
    const selectedId = selectedCellId ?? "";
    map.setPaintProperty(FILL_LAYER_ID, "fill-color", [
      "case",
      ["==", ["get", "cell_id"], selectedId],
      "#f0bc87",
      ["match", ["get", "risk_level"], "high", "#c65d50", "medium", "#d3944e", "low", "#4a9a77", "#748492"],
    ]);
    map.setPaintProperty(FILL_LAYER_ID, "fill-opacity", ["case", ["==", ["get", "cell_id"], selectedId], 0.78, 0.48]);
    map.setPaintProperty(LINE_LAYER_ID, "line-color", ["case", ["==", ["get", "cell_id"], selectedId], "#ffe1bd", "#a6b3b4"]);
    map.setPaintProperty(LINE_LAYER_ID, "line-width", ["case", ["==", ["get", "cell_id"], selectedId], 2.5, 0.8]);
  }, [selectedCellId]);

  return (
    <div className="risk-map-shell">
      <div
        className="risk-map-canvas"
        ref={containerRef}
        role="application"
        aria-label="Interactive map of API-provided risk grid polygons. Use the map controls to zoom and select a cell."
      />
      {mapError && <div className="map-render-error" role="alert">Map rendering error: {mapError}</div>}
    </div>
  );
}
