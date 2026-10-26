// Fits API polygon coordinates ([longitude, latitude]) into an SVG viewBox.
// This is a schematic plot of the API geometry only; there is no basemap.

export type Bounds = { minLon: number; minLat: number; maxLon: number; maxLat: number };
type Ring = readonly (readonly number[])[];
type Polygon = { geometry: { coordinates: readonly Ring[] } };

export function boundsOf(polygons: readonly Polygon[]): Bounds | null {
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  for (const { geometry } of polygons) {
    for (const [lon, lat] of geometry.coordinates[0] ?? []) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }
  return Number.isFinite(minLon) ? { minLon, minLat, maxLon, maxLat } : null;
}

export type Projection = { width: number; height: number; path: (rings: readonly Ring[]) => string };

/**
 * Equirectangular projection scaled by cos(mid-latitude), so cells keep their
 * shape at this latitude. North is up. `width` is fixed; height follows the aspect.
 */
export function makeProjection(bounds: Bounds, width = 600, padding = 12): Projection {
  const kx = Math.cos((((bounds.minLat + bounds.maxLat) / 2) * Math.PI) / 180);
  const spanX = Math.max((bounds.maxLon - bounds.minLon) * kx, 1e-9);
  const spanY = Math.max(bounds.maxLat - bounds.minLat, 1e-9);
  const scale = (width - 2 * padding) / spanX;
  const height = Math.round(spanY * scale + 2 * padding);
  const x = (lon: number) => padding + (lon - bounds.minLon) * kx * scale;
  const y = (lat: number) => padding + (bounds.maxLat - lat) * scale;
  const ring = (r: Ring) => r.map(([lon, lat], i) => `${i ? "L" : "M"}${x(lon).toFixed(2)},${y(lat).toFixed(2)}`).join("") + "Z";
  return { width, height, path: (rings) => rings.map(ring).join("") };
}
