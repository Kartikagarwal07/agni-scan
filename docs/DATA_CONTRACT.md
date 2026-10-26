
# AGNI-SCAN Data Contract

Version: 1.0.0

## Purpose

This document defines the shared format used by the
geospatial pipeline, backend API, and frontend dashboard.

## Risk Grid Response

GET /api/grid returns a GeoJSON FeatureCollection.

Coordinate system: WGS84 (EPSG:4326)
Coordinate order: [longitude, latitude]

## Example (MOCK DATA — NOT REAL SATELLITE RESULTS)

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "PB-001",
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [75.80, 30.90],
            [75.81, 30.90],
            [75.81, 30.91],
            [75.80, 30.91],
            [75.80, 30.90]
          ]
        ]
      },
      "properties": {
        "cell_id": "PB-001",
        "district": "Ludhiana",
        "risk_score": 82,
        "risk_level": "high",
        "observed_fire_count": 0,
        "evidence_completeness": 0.75,
        "verification_status": "unverified",
        "analysis_date": "2026-10-26"
      }
    }
  ]
}
```

## Required Properties

| Field | Type | Rules |
| --- | --- | --- |
| cell_id | string | Unique, stable grid ID |
| district | string | Punjab district |
| risk_score | number or null | 0–100 or null |
| risk_level | string | low, medium, high, unknown |
| observed_fire_count | integer | 0 or greater |
| evidence_completeness | number | 0–1 |
| verification_status | string | unverified, scheduled, verified_fire, verified_no_fire |
| analysis_date | string | YYYY-MM-DD |

## Risk Level Thresholds

- low: 0–39
- medium: 40–69
- high: 70–100
- unknown: risk_score is null

## Validation Rules

1. Every Feature has Polygon geometry.
2. Polygon rings must be closed.
3. Feature.id equals properties.cell_id.
4. Longitude comes before latitude.
5. Missing risk scores must be null, not zero.
6. Zero detections does not prove zero burning.
7. Mock data must be clearly labeled.

## Interpretation

risk_score is a heuristic verification-priority score,
NOT a scientifically validated probability of burning.

## Ownership

- Data: generate conforming GeoJSON.
- Backend: validate, store, and serve the data.
- Frontend: display the agreed fields.
  