# AGNI-SCAN data pipeline

Python pipeline that turns **locally supplied** NASA FIRMS VIIRS fire detections and
**user-supplied** Punjab boundaries into the risk-grid GeoJSON defined in
[`docs/DATA_CONTRACT.md`](../docs/DATA_CONTRACT.md) (v1.0.0), which the backend serves at `GET /api/grid`.

> **What the score means.** `risk_score` is a heuristic **verification-priority** score
> for scheduling field checks. It is **not** a probability of burning or of undetected fire.
> `observed_fire_count` counts satellite detections only, and **zero detections do not prove zero
> burning**: cloud or smoke cover, overpass timing, and small or brief fires all cause missed
> detections. When the evidence is insufficient, `risk_score` is `null` and `risk_level` is `"unknown"`.

The pipeline downloads nothing and ships no real data. Everything under `fixtures/synthetic/` is
**fabricated test data** and is labeled as such in the file names, the GeoJSON markers, and a
`data_label=SYNTHETIC` column.

---

## 1. Setup (Windows PowerShell)

Requires Python 3.10 or newer (tested with 3.12.10 on Windows 11).

```powershell
cd C:\path\to\agni-scan\data-pipeline
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

If `Activate.ps1` is blocked, allow local scripts for your user once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or skip activation and call
`.\.venv\Scripts\python.exe` directly in every command below.

`requirements.txt` pins the exact versions this was verified with (shapely 2.2.0, pyproj 3.8.0,
pytest 8.4.2). Both shapely and pyproj ship Windows wheels, so you don't need GDAL, conda, or geopandas.

## 2. Run the tests

```powershell
python -m pytest
```

Expected output: `117 passed`.

## 3. Synthetic demo

```powershell
python -m agni_pipeline demo            # writes to .\output\demo
python -m agni_pipeline validate .\output\demo\risk_grid.geojson
```

Expected output:

```text
[SYNTHETIC DEMONSTRATION DATA - NOT REAL SATELLITE EVIDENCE]
Analysis window : 2026-10-20 .. 2026-10-26 (7 days, UTC acq_date)
Grid cells      : 48 x 5000 m (EPSG:32643)
Detections      : 10 in window, 9 assigned, 1 outside region, 0 rows rejected
Risk levels     : high=1, medium=0, low=47, unknown=0
Contract check  : PASSED (docs/DATA_CONTRACT.md v1.0.0)
  geojson      output\demo\risk_grid.geojson
  explanations output\demo\score_explanations.csv
  assignments  output\demo\detection_assignments.csv
  rejections   output\demo\rejected_rows.csv
output\demo\risk_grid.geojson: conforms to docs/DATA_CONTRACT.md (48 features)
```

To see `unknown` cells, run on the window file alone, with no history and no cell evidence. Every
cell with zero detections then lacks independent evidence and gets `risk_score: null`:

```powershell
python -m agni_pipeline run `
  --firms .\fixtures\synthetic\synthetic_firms_viirs_window.csv `
  --boundary .\fixtures\synthetic\synthetic_state_boundary.geojson `
  --districts .\fixtures\synthetic\synthetic_districts.geojson `
  --analysis-date 2026-10-26 --output-dir .\output\demo-window-only
```

## 4. Running on real data

Place the real files in `data-pipeline\data\` (git-ignored), then:

```powershell
python -m agni_pipeline run `
  --firms .\data\fire_nrt_SV-C2.csv `
  --firms .\data\fire_nrt_J1V-C2.csv `
  --boundary .\data\punjab_state.geojson `
  --districts .\data\punjab_districts.geojson --district-name-field district `
  --analysis-date 2026-10-26 --window-days 7 --cell-size-m 5000 `
  --history-firms .\data\fire_archive_SV-C2_2024_2025.csv `
  --output-dir .\output\2026-10-26
```

| Option | Meaning |
| --- | --- |
| `--firms CSV` (repeatable, required) | FIRMS VIIRS CSV(s) covering the analysis window, e.g. one each for S-NPP, NOAA-20 and NOAA-21. Overlapping rows are de-duplicated. |
| `--boundary GEOJSON` (required) | Authoritative Punjab state boundary in WGS84. |
| `--districts GEOJSON` | Authoritative district boundaries in WGS84. Required unless `--allow-missing-districts` is set. |
| `--district-name-field` | Property holding the district name (default `district`). |
| `--analysis-date`, `--window-days` | Window = the `window-days` days ending on `analysis-date`, inclusive, by FIRMS `acq_date` (UTC). |
| `--cell-size-m` | Grid cell size in metres, 100–50000 (default 5000). |
| `--history-firms CSV` (repeatable) | Optional earlier-season detections. Only dates **before** the window are used. |
| `--cell-evidence CSV` | Optional per-cell values such as `cropland_fraction` (see §6). |
| `--config JSON` | Scoring config (default: [`src/agni_pipeline/default_scoring.json`](src/agni_pipeline/default_scoring.json)). |
| `--synthetic` | Force the output to be labeled synthetic. |
| `--strict` | Fail if any FIRMS row is rejected, instead of reporting it and continuing. |
| `--repair-geometry` | Repair invalid boundary polygons with `make_valid` instead of failing. |
| `--allow-missing-districts` | Write `district: "UNAVAILABLE"` instead of failing. **The output then does not conform to the contract** (see §8). |

Exit code `0` means success with output validated against the contract. Exit code `1` means an input
or contract error, and the message names the file, line, or field. Exit code `2` means a usage error.

### Output files

| File | Content |
| --- | --- |
| `risk_grid.geojson` | Contract FeatureCollection plus a top-level `metadata` member (provenance, window, grid, scoring parameters, input SHA-256 hashes, counts, warnings). |
| `score_explanations.csv` | One row per cell: every component's value and weight, completeness, score, and the reason (`scored`, `insufficient_evidence`, `zero_detections_without_independent_evidence`). |
| `detection_assignments.csv` | Every in-window detection that passed the filters, with its cell or `outside_region`. |
| `rejected_rows.csv` | Every rejected input row, with file, line number and reason. |

## 5. Input requirements

### FIRMS VIIRS CSV

Required columns: `latitude`, `longitude`, `acq_date`. The optional columns `acq_time`,
`confidence`, `satellite`, `instrument`, `frp`, `type`, `daynight` and `version` are validated
when present.

The following documented variations are accepted:

- NRT files.
- Standard-processing archive files with `type`.
- Upper-case headers, as in shapefile/DBF exports.
- A UTF-8 BOM.
- `confidence` given as `l`/`n`/`h` or `low`/`nominal`/`high`.
- `acq_time` without leading zeros (`56` means `00:56`).

Rows are rejected, with the line number and reason, for the following:

- Non-numeric, non-finite or out-of-range lat/lon.
- A date that isn't a valid `YYYY-MM-DD`.
- A bad HHMM time.
- MODIS-style numeric confidence, or a non-VIIRS `instrument`.
- Negative FRP.
- An unknown `type`.
- The wrong field count.

A missing required column fails the whole file.

The default quality filters drop `low` confidence detections, detections without a confidence value,
and archive `type` 1, 2 and 3 (volcano, static land source, offshore). You can change these in the
config file.

### Boundary GeoJSON (state and districts)

- Polygon or MultiPolygon features in WGS84 `[longitude, latitude]` (RFC 7946). A legacy `crs`
  member is accepted only if it names CRS84 or EPSG:4326. Projected files are rejected with a
  reprojection hint, for example `ogr2ogr -t_srs EPSG:4326 out.geojson in.geojson`.
- Geometries must be valid, or you can pass `--repair-geometry`.
- The extent must fall inside a loose Punjab envelope (73.5–77.5°E, 29.3–32.8°N). This catches
  swapped coordinate order and mislabeled projected coordinates.
- If the state area differs from the reference 50,362 km² by more than 15%, you get a warning,
  because it may be the wrong file.
- If districts cover less than 99% of the state, you get a warning. Any cell that overlaps no
  district stops the run, unless `--allow-missing-districts` is set.

## 6. Method

**Grid.**
- Cells are squares in WGS 84 / UTM 43N (EPSG:32643), aligned to the CRS origin, then clipped to
  the state boundary.
- Output is reprojected to EPSG:4326, with exterior rings counter-clockwise per RFC 7946.
- Cell IDs come only from position and cell size, so they stay stable across runs and across
  boundary-file revisions: `PB-5000M-N00681-E00118` means row `floor(northing/5000)` and column
  `floor(easting/5000)`.
- A square that clipping splits into disjoint pieces becomes one Polygon cell per piece, with the
  suffix `-P1`, `-P2`, and so on. This is needed because the contract requires Polygon, not
  MultiPolygon.
- Synthetic runs use the prefix `SYNTH-PB-`, so a synthetic cell can't be mistaken for a real one
  even if the metadata is dropped.

**Detection assignment.** Each detection's pixel centre is projected and placed using half-open
cells `[x0, x0+size) × [y0, y0+size)`. A point on a shared edge or corner therefore counts in
exactly one cell. Points outside the state boundary are excluded and counted in
`metadata.detections.outside_region`. Points on the boundary itself count.

**District.** Each cell takes the district that covers the largest share of its area. Districts are
never inferred or guessed.

**Score.** Each configured component yields a value in [0, 1] or is *unavailable*:

| Component (default weight) | Source | Value |
| --- | --- | --- |
| `observed_detections` (0.5) | FIRMS, analysis window | `min(count / 5, 1)` |
| `historical_detections` (0.3) | `--history-firms` | `min(count / 20, 1)`; unavailable if no history file |
| `cropland_fraction` (0.2) | `--cell-evidence` column | as supplied (0–1); blank/`NA` means unavailable |

- `evidence_completeness` is the sum of the weights of available components divided by the total weight.
- `risk_score` is `round_half_up(100 × weighted mean of available components)`. Missing evidence is
  never counted as zero.
- The score is `null` / `unknown` when completeness is below `min_evidence_completeness` (0.5).
- The score is also `null` / `unknown` when a cell has **zero detections and no independent evidence**
  (history or cell attributes).
- Levels follow the contract thresholds: low 0–39, medium 40–69, high 70–100.

The weights are expert-set defaults. They have not been fitted or validated against ground truth,
and you can tune them in the JSON config. With the defaults, a cell with zero window detections can
reach at most 50 (medium). Detected fires come first in the verification queue, and a "low" score
means "lower relative priority", never "no burning".

The cell-evidence CSV has a `cell_id` column plus one column per `cell_attribute` component, with
values in [0, 1]. It must be prepared for the same `--cell-size-m`, because IDs encode the size.

## 7. Layout

```text
data-pipeline/
  pyproject.toml, requirements.txt, README.md
  src/agni_pipeline/
    firms.py        FIRMS CSV ingestion, validation, de-duplication, quality filters
    boundary.py     boundary/district GeoJSON validation, CRS handling, projection
    grid.py         stable projected grid, clipping, detection and district assignment
    scoring.py      configurable verification-priority heuristic
    evidence.py     optional per-cell evidence CSV
    contract.py     contract GeoJSON builder and validator
    pipeline.py     end-to-end orchestration and output files
    cli.py          `agni-pipeline run | demo | validate`
    default_scoring.json
  fixtures/synthetic/   SYNTHETIC test inputs (not real data)
  tests/                pytest suite
```

## 8. Notes for backend and frontend (contract points)

- **Top-level `metadata` member.** The output FeatureCollection carries a top-level `metadata`
  foreign member (allowed by RFC 7946 §6.1). The contract example doesn't show it, but it is how
  rule 7 ("mock data must be clearly labeled") is met without adding per-feature properties. Please
  preserve or forward it. Key fields are `metadata.synthetic` (boolean) and
  `metadata.data_provenance`, which is either `SYNTHETIC_DEMONSTRATION_NOT_REAL_SATELLITE_DATA` or
  `PROCESSED_USER_SUPPLIED_FIRMS_OBSERVATIONS`.
- **Cell ID format.** Cell IDs look like `PB-5000M-N00681-E00118`, not `PB-001`. The contract only
  requires a unique, stable string. At 1 km a sequential 3-digit ID can't cover Punjab (~50k
  cells), and a sequential ID wouldn't be stable when the boundary changes.
- **`district` cannot be null.** The contract types `district` as a required Punjab-district
  string and does not allow null or "unavailable". The pipeline therefore refuses to run without
  complete district boundaries. `--allow-missing-districts` writes `"UNAVAILABLE"`, records it in
  `metadata.contract_deviations`, and the default validator flags it. Supporting this properly needs
  a contract change agreed by the team.
- **`verification_status`.** The pipeline always emits `verification_status: "unverified"`. Field
  results belong to the backend.

## 9. Real datasets you must supply

None of these are included, and the pipeline never fabricates them:

1. **NASA FIRMS VIIRS 375 m active-fire CSVs** (S-NPP, NOAA-20, NOAA-21) for the analysis window,
   downloaded by you from <https://firms.modaps.eosdis.nasa.gov/>, plus optional archive files for
   earlier seasons.
2. **Authoritative Punjab state boundary** (for example from Survey of India or the Punjab Remote
   Sensing Centre), converted to WGS84 GeoJSON.
3. **Authoritative Punjab district boundaries** for the current district set, with names in a
   consistent property.
4. Optionally, **per-cell cropland/paddy fraction** derived from an authoritative land-cover
   product, keyed by this pipeline's cell IDs.
