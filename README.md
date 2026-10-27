# AGNI-SCAN

> **From satellite signals to smarter field visits.**

AGNI-SCAN is a transparent verification-priority dashboard for possible crop-residue burning in Punjab. It does **not** claim that a satellite detection proves burning. Instead, it helps field teams decide **which 5 km grid cell to verify first**, explains why, and records what inspectors find.

## Why it matters

Field teams cannot inspect every location at once. A satellite heat signal can be caused by several sources and may be missed because of clouds, smoke, timing, or sensor limits. AGNI-SCAN turns these imperfect observations into an explainable queue for human verification.

```text
NASA FIRMS observations + historical recurrence + land-cover context
                              │
                              ▼
                    explainable 5 km grid
                              │
                              ▼
              ranked field-verification priorities
                              │
                              ▼
             inspector outcome stored for auditability
```

## What the dashboard does

- Displays a Punjab-wide grid with high, medium, low, and unknown verification priorities.
- Explains each selected cell: observed detections, evidence completeness, risk score, priority rank, and provenance.
- Filters priorities by district, date, and risk level.
- Preserves the data source and synthetic/real-data label throughout the interface.
- Records field outcomes: **fire evidence found**, **no fire evidence found**, or **inconclusive**.
- Persists inspections in Supabase when configured, rather than losing them when the server restarts.

## Evidence model

The default heuristic is intentionally simple and inspectable:

| Evidence | Role | Rule |
| --- | --- | --- |
| Recent NASA FIRMS VIIRS detections | Main score | Weight 0.5; five or more detections saturate this component. |
| Historical FIRMS recurrence | Secondary score | Weight 0.3; each season is capped separately, then seasons are averaged. |
| ESA WorldCover 2021 cropland fraction | Tie-break only | Orders equal-scoring cells with fire evidence; never increases a score or risk level. |

`priority_rank = 1` means **verify first**. A score is a field-work priority heuristic—not a probability, legal finding, or confirmation of burning.

## Real-data workflow

The reproducible pipeline can use:

- **NASA FIRMS VIIRS** observations from Suomi-NPP, NOAA-20, and NOAA-21.
- **Survey of India / NWIC** Punjab state and district boundaries.
- **ESA WorldCover 10 m (2021 v200)** general cropland coverage, class 40, under CC BY 4.0.

One evaluated local run produced **2,256 5 km cells**: 54 high, 187 medium, and 2,015 low priorities. Raw detections, boundary downloads, land-cover tiles, processed real outputs, and API keys are deliberately excluded from Git.

See [`data-pipeline/README.md`](data-pipeline/README.md) for reproducibility, provenance, checksums, and data-preparation commands.

## Quick start

```powershell
git clone https://github.com/Kartikagarwal07/agni-scan.git
cd agni-scan
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) and select **Dashboard**.

The committed default is a clearly labelled synthetic demonstration dataset, so the repository runs safely without private data.

## Use a reviewed local real grid

Keep processed real output outside Git and set this in `.env.local`:

```text
AGNI_GRID_PATH=data-pipeline/output/real/risk_grid.geojson
```

The API validates the selected GeoJSON against the shared data contract before it is served. Remove the setting to return to the synthetic demonstration grid.

## Persistent field inspections

AGNI-SCAN uses a Supabase PostgreSQL table when server-only Supabase credentials are configured. Browser clients never receive the database secret key; production refuses to fall back to temporary memory when persistent storage is missing.

Setup instructions: [`docs/SUPABASE_SETUP.md`](docs/SUPABASE_SETUP.md)

## API surface

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Backend availability check |
| `GET /api/grid` | Filtered GeoJSON grid with provenance metadata |
| `GET /api/grid/:id` | One grid cell by stable ID |
| `GET /api/priorities` | Paginated verification queue, respecting pipeline priority ranks |
| `GET /api/inspections` | Persistent inspection history, optionally for one cell |
| `POST /api/inspections` | Validated, authorized field-verification result |

The exact API request and response shapes are in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md). The GeoJSON data requirements are in [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md).

## Verification

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

The data pipeline has its own offline test suite under `data-pipeline/tests`.

## Responsible-use notes

- FIRMS detections are thermal anomalies, **not confirmed crop-residue-burning events**.
- Zero detections do not prove that burning did not happen.
- WorldCover reports general cropland, **not paddy-specific coverage**.
- The current authoritative district source represents Malerkotla within Sangrur; this limitation is documented in pipeline provenance.
- The final decision remains with trained human inspectors and relevant authorities.

## Project structure

```text
app/             Next.js interface and route handlers
lib/             Contract validation, data loading, ranking, inspection storage
data-pipeline/   Reproducible boundaries, FIRMS, scoring, and evidence workflow
docs/            Shared API, data, and deployment documentation
supabase/        Versioned database migration for persistent inspections
```

## Credits

- NASA FIRMS for VIIRS active-fire observations.
- ESA WorldCover project / modified Copernicus Sentinel data processed by the ESA WorldCover consortium.
- Survey of India / NWIC for boundary data used in local processing.

---

**AGNI-SCAN does not replace field verification—it helps make the next field visit more informed, explainable, and auditable.**
