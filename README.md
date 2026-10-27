# AGNI-SCAN

AGNI-SCAN turns satellite fire observations into a transparent field-verification queue for Punjab. It helps teams decide **where to inspect first**, while keeping the distinction between a satellite heat signal and confirmed crop-residue burning visible at every stage.

The repository combines a Next.js dashboard, contract-tested API routes, and a reproducible Python data pipeline. The default website is a safe synthetic demonstration. A locally generated real-data output can be selected through a server-only environment variable after it has been reviewed.

## Getting Started

```powershell
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) for the landing page or [http://localhost:3000/dashboard](http://localhost:3000/dashboard) for the dashboard.

## Demo API

The backend implements the shared API and data contracts in `docs/`. `GET /api/grid`
serves the deterministic synthetic grid generated in `data-pipeline/demo/`, including
its provenance metadata and safety disclaimer. It is not satellite data, Punjab
geography, or a validated burning estimate.

`POST /api/inspections` uses in-memory demo storage, so records reset when the
server restarts. In production it requires an `x-agni-scan-write-token` header
matching the server-only `AGNI_SCAN_WRITE_TOKEN` environment variable. Do not
deploy the demo write store publicly; replace it with authenticated persistent
storage first.

By default, `GET /api/grid` serves the committed synthetic grid. To serve a locally generated real-data output, set `AGNI_GRID_PATH` in `.env.local`:

```text
AGNI_GRID_PATH=C:\path\to\data-pipeline\output\real-2026-10-26-20261027-060500\risk_grid.geojson
```

Relative paths resolve from the repository root. The API validates the selected GeoJSON at startup and fails clearly if it is missing or violates the shared data contract. The path and raw files stay server-side; the dashboard receives only the validated grid and its provenance metadata. Remove `AGNI_GRID_PATH` to return to the synthetic demo.

The reproducible real-data workflow is documented in [`data-pipeline/README.md`](data-pipeline/README.md). It uses official Punjab boundaries distributed through NWIC and NASA FIRMS VIIRS observations. Those observations identify thermal anomalies and support prioritisation; they do not, by themselves, prove crop-residue burning.

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Run API validation tests with `npm test`.

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Project map

- `app/` — landing page, dashboard, and API route handlers.
- `lib/api-core.ts` — grid loading, contract validation, filtering, and inspection rules.
- `lib/dashboard/` — browser API clients, formatting, projection, and provenance display.
- `data-pipeline/` — boundary preparation, FIRMS ingestion, scoring, contract checks, and reproducible runs.
- `docs/` — API and data contracts shared by the team.

## Verification

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

The data pipeline has its own offline test suite and setup instructions under [`data-pipeline/`](data-pipeline/).

## API surface

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Service health check |
| `GET /api/grid` | Filtered GeoJSON risk grid with provenance metadata |
| `GET /api/grid/:id` | One grid cell by stable ID |
| `GET /api/priorities` | Paginated verification priorities |
| `GET /api/inspections` | Recorded inspections, optionally filtered by cell |
| `POST /api/inspections` | Validate and record a field result |

The exact request and response shapes live in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md). Data provenance and risk-grid requirements live in [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md).

## How the score is used

Each grid cell receives a verification-priority score from available evidence such as recent FIRMS detections, historical detections, and optional cropland attributes. Evidence completeness is shown separately from the score. Missing evidence is never silently treated as zero, and `unknown` means that the system lacks enough evidence to rank the cell reliably.

The score is a field-work heuristic. It is not a probability, legal finding, or proof that burning occurred. Field teams record one of three outcomes: fire evidence found, no fire evidence found, or inconclusive.

## Team workflow

Create focused branches from the latest `main`, run the relevant checks, and open a pull request before merging. Keep `.env.local`, raw FIRMS downloads, generated outputs, and private credentials out of Git. Preserve the provenance metadata whenever data moves between the pipeline, API, and dashboard.

AGNI-SCAN is designed to make the next field visit more informed, more explainable, and easier to verify.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
