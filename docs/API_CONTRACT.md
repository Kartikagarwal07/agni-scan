
# AGNI-SCAN API Contract

Version: 1.0.0

Base URL: `/api`

Response format: JSON unless specified otherwise.

## 1. GET /api/health

Purpose: Check backend availability.

Success (200):

```json
{"status":"ok","service":"agni-scan"}
```

## 2. GET /api/grid

Purpose: Return risk cells as GeoJSON.

Optional query parameters:

- district: district name
- date: YYYY-MM-DD
- risk_level: low, medium, high, unknown

Success (200): GeoJSON FeatureCollection matching
`docs/DATA_CONTRACT.md`.

Empty result:

```json
{"type":"FeatureCollection","features":[]}
```

## 3. GET /api/grid/:id

Purpose: Return one risk cell.

Success (200): One GeoJSON Feature.
Not found (404): Standard error object.

## 4. GET /api/priorities

Purpose: Rank cells for field verification.

Optional query parameters:

- district: district name
- limit: 1–100 (default 20)
- offset: 0 or greater (default 0)

Success (200):

```json
{
  "items": [
    {
      "cell_id": "PB-001",
      "district": "Ludhiana",
      "risk_score": 82,
      "risk_level": "high",
      "evidence_completeness": 0.75,
      "verification_status": "unverified"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

## 5. GET /api/inspections

Purpose: List field inspections.

Optional query parameters:

- cell_id: grid cell ID
- limit: 1–100 (default 20)
- offset: 0 or greater (default 0)

Success (200):

```json
{"items":[],"total":0,"limit":20,"offset":0}
```

## 6. POST /api/inspections

Purpose: Save a field verification result.

Request:

```json
{
  "cell_id": "PB-001",
  "result": "fire_evidence_found",
  "notes": "Example field report — mock data"
}
```

Allowed results:

- fire_evidence_found
- no_fire_evidence_found
- inconclusive

Success (201):

```json
{
  "id": "inspection-001",
  "cell_id": "PB-001",
  "result": "fire_evidence_found",
  "notes": "Example field report — mock data",
  "created_at": "2026-10-26T14:30:00Z"
}
```

The backend generates `created_at` in UTC.

## Standard Error Format

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request parameters"
  }
}
```

HTTP statuses:

- 200: successful GET
- 201: inspection created
- 400: invalid request
- 404: resource not found
- 500: unexpected server error

## Shared Rules

1. Property names use snake_case.
2. Dates use YYYY-MM-DD.
3. Timestamps use UTC ISO 8601.
4. Risk scores are verification-priority heuristics.
5. Examples are mock data, not actual observations.
6. Contract changes require team agreement.
7. Write endpoints require authorization before public deployment.
  