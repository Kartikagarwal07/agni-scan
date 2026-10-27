
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
        "priority_rank": 1,
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
| priority_rank | integer, optional | 1 or greater. Lower values appear first in the verification queue. |
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
8. `priority_rank`, when supplied, orders cells without changing `risk_score`, `risk_level`, or `evidence_completeness`.

## Optional priority order

`priority_rank` lets the data pipeline resolve ties without changing the risk score. The current
pipeline uses cropland only to break ties between cells that have recent or historical fire
evidence. Cells without fire evidence remain low priority; cropland does not promote them.

The field is optional so existing grids remain valid. When it is absent, consumers should order
cells by descending `risk_score`, place null scores last, then use a stable cell-ID order.

## Interpretation

risk_score is a heuristic verification-priority score,
NOT a scientifically validated probability of burning.

## Ownership

- Data: generate conforming GeoJSON.
- Backend: validate, store, and serve the data.
- Frontend: display the agreed fields.
