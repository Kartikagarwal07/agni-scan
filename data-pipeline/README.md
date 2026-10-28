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

Only `prepare-cropland` (§4.6) reads rasters. It needs the optional `landcover` extra (rasterio, which
also ships Windows wheels):

```powershell
python -m pip install -e ".[landcover]"
```

## 2. Run the tests

```powershell
python -m pytest
```

Expected output: `167 passed`. No test needs the network or a FIRMS key. Without the `landcover`
extra, the 6 cropland tests are skipped.

## 3. Deterministic demo grid

[`demo/risk_grid.geojson`](demo/risk_grid.geojson) is a committed reference file that follows the
contract. The backend and frontend can use it right away. It is built from the synthetic fixtures,
and the same command always produces the same bytes:

- There is no wall-clock timestamp (`metadata.generated_at` is `null` and `metadata.deterministic`
  is `true`).
- Metadata records input file names, not paths.
- Key order is fixed, coordinates are rounded to 6 decimals, and files are UTF-8 with LF line
  endings, enforced by [`.gitattributes`](.gitattributes).

It contains 48 cells: one each of `high` (76) and `medium` (56), 42 `low`, and 4 `unknown`
(`risk_score: null`). Districts are `SYNTHETIC-DISTRICT-WEST` and `SYNTHETIC-DISTRICT-EAST`, and
every ID starts with `SYNTH-PB-`.

```powershell
python -m agni_pipeline demo --check                  # committed file == fresh run, and contract-valid
python -m agni_pipeline validate .\demo\risk_grid.geojson
python -m agni_pipeline demo --output-dir .\demo      # regenerate after an intentional change
python -m agni_pipeline demo                          # scratch copy in .\output\demo
```

Expected output of `demo --output-dir .\demo`:

```text
[SYNTHETIC DEMONSTRATION DATA - NOT REAL SATELLITE EVIDENCE]
Analysis window : 2026-10-20 .. 2026-10-26 (7 days, UTC acq_date)
Grid cells      : 48 x 5000 m (EPSG:32643)
Detections      : 10 in window, 9 assigned, 1 outside region, 0 rows rejected
Risk levels     : high=1, medium=1, low=1, unknown=45
Contract check  : PASSED (docs/DATA_CONTRACT.md v1.0.0)
Detection funnel (window files; every row is accounted for):
  file                              rows_read  rejected_invalid  valid  duplicates  ...  outside_window  outside_region  in_dropped_sliver  assigned
  synthetic_firms_viirs_window.csv         13                 0     13           1  ...               1               1                  0         9
  TOTAL                                    13                 0     13           1  ...               1               1                  0         9
  geojson      demo\risk_grid.geojson
  explanations demo\score_explanations.csv
  assignments  demo\detection_assignments.csv
  rejections   demo\rejected_rows.csv
  funnel       demo\detection_funnel.csv
```

**Validation approach.** Every run validates its own output against `DATA_CONTRACT.md` before
writing anything, and fails (exit code 1) on any violation. These are the checks:

- **Rules 1–4:** Polygon only; closed rings with at least 4 positions; `Feature.id` equals
  `cell_id`; `[longitude, latitude]` order, checked against the Punjab envelope.
- **Properties:** exactly the 8 contract properties, each with its type and range.
- **Score and level:** `risk_level` must match `risk_score` under the contract thresholds, and a
  missing score must be `null`.
- **Uniqueness:** no duplicate `cell_id`.
- **Labeling (rule 7):** a provenance label is required, and synthetic output must have the
  `SYNTH-` prefix and a disclaimer.

The same checks run standalone through `agni-pipeline validate <file>`. Add
`--no-require-metadata` for files without the metadata block, such as the backend's `DEMO_GRID`. On
top of that, `demo --check` guards against drift: the pytest suite fails if the committed demo no
longer matches a fresh run.

The demo does not use the historical FIRMS fixture. That leaves zero-detection cells with no
independent fire evidence (cropland is only a tie-break), which shows how `unknown` is produced. Add
`--history-firms .\fixtures\synthetic\synthetic_firms_viirs_history.csv` to a `run` command to see
the historical component.

## 4. Running on real data

Real inputs and results live in `data-pipeline\data\` and `data-pipeline\output\`. Both are
git-ignored, so raw data never reaches GitHub. The one exception is
`output\real\risk_grid.geojson`: the processed grid the deployed site serves. Write a reviewed run there
(`--output-dir output\real`) and commit only that file. Its companion CSVs stay ignored.

### 4.1 One command (reproducible)

Prerequisites:
- a free NASA FIRMS MAP_KEY in the repository's `.env.local` as `FIRMS_MAP_KEY=...`;
- the Survey of India boundary downloads from NWIC: `state_nwic_geojson.zip` and
  `district_nwic_geojson.zip` (see §9).

```powershell
# Latest days, ending today (UTC)
.\scripts\real-data.ps1 -StateZip $HOME\Downloads\state_nwic_geojson.zip -DistrictZip $HOME\Downloads\district_nwic_geojson.zip

# Fixed dates: UTC acq_date 2026-10-23 .. 2026-10-26
.\scripts\real-data.ps1 -StateZip ... -DistrictZip ... -StartDate 2026-10-23 -Days 4

# Re-run an earlier download without contacting FIRMS
.\scripts\real-data.ps1 -StateZip ... -DistrictZip ... -FirmsDir data\firms\20261027-060500
```

The script runs three steps:

1. **`prepare-boundaries`.** Reads each zip in memory, without extracting it, and keeps Punjab
   (`stcode == "03"`). It reprojects the boundaries from the files' EPSG:7755 (India LCC) to WGS84
   and writes `data\boundaries\punjab_state.geojson` and `punjab_districts.geojson`. Each output
   records the source zip, its SHA-256 and the source CRS. This step is skipped when the files
   already exist; pass `-Force` to rebuild them.
2. **`fetch-firms`.** Downloads `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT` and `VIIRS_NOAA21_NRT` for the
   state's bounding box (padded by 0.05° and rounded outward to 0.01°) into
   `data\firms\<UTC timestamp>\`. It also writes `manifest.json`, which records the date range, the
   bbox, the row count and SHA-256 of each file, and the request URL with the key replaced by
   `<MAP_KEY>`.
3. **`run`.** Builds the grid for exactly the fetched dates, into
   `output\real-<end date>-<fetch timestamp>\`.

**What "reproducible" means here.** Re-running with `-FirmsDir` on a saved download gives an
identical grid. Re-downloading the same dates later is not guaranteed to give identical rows,
because FIRMS replaces near-real-time (NRT) data with standard-processing (SP) data after a few
weeks. Keep the `data\firms\<timestamp>\` folder of any run you report.

Results built from FIRMS must credit NASA FIRMS wherever they are shown.

### 4.2 Individual commands

```powershell
python -m agni_pipeline prepare-boundaries <state.zip> --output data\boundaries\punjab_state.geojson --kind state --value 03
python -m agni_pipeline prepare-boundaries <district.zip> --output data\boundaries\punjab_districts.geojson `
  --kind districts --value 03 --expect-count 23 --state data\boundaries\punjab_state.geojson
python -m agni_pipeline fetch-firms --output-dir data\firms\my-fetch --boundary data\boundaries\punjab_state.geojson --days 5
```

`fetch-firms` reads `FIRMS_MAP_KEY` from the environment first, then from `.env.local`
(`--env-file` to change it). The Area API allows 1 to 5 days per request
(`--start-date` = first day) and 5,000 transactions per 10 minutes per key.

### 4.3 Detection funnel (reconciling counts)

Every run writes `detection_funnel.csv`: one row per FIRMS file plus a TOTAL row. The run fails if
these two identities do not hold:

```text
rows_read = rejected_invalid + valid
valid     = duplicates + removed_fire_type + removed_low_confidence + removed_missing_confidence
          + outside_window + outside_region + in_dropped_sliver + assigned
```

Worked example, real run for 2026-10-23 .. 2026-10-26 (fetch `20261027-060500`):

| File | rows_read | removed_low_confidence | outside_region | assigned (in Punjab) |
| --- | ---: | ---: | ---: | ---: |
| VIIRS_SNPP_NRT | 442 | 13 | 260 | 169 |
| VIIRS_NOAA20_NRT | 501 | 15 | 265 | 221 |
| VIIRS_NOAA21_NRT | 403 | 14 | 233 | 156 |
| **TOTAL** | **1,346** | **42** | **758** | **546** |

So 1,346 rows read = 42 low-confidence + 758 outside Punjab + 546 assigned. No rows were invalid,
duplicated or outside the window.

Notes from reconciling the first manual download of the same dates:
- Its box (`73.8,29.5,77.0,32.6`) was slightly larger, so it had 1,398 rows: 44 low-confidence and
  808 outside Punjab. The Punjab result was identical: the same 546 detections and the same 2,256
  cells.
- The "44" were exactly the rows with `confidence = l`. The default filter keeps `nominal` and
  `high`; see `firms_filters` in the scoring config.
- FIRMS CSVs have no trailing newline, so `wc -l` under-counts each file by one. Use the funnel's
  `rows_read`, not a line count.

### 4.4 Manual `run`

With your own files in `data-pipeline\data\`:

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
| `--history-firms CSV` (repeatable) | Optional earlier-season detections, e.g. from `scripts\history-firms.ps1` (§4.5). Only dates **before** the window are used, scored per season. |
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
| `detection_funnel.csv` | Where every input row went, per FIRMS file (see §4.3). |

### 4.5 Historical seasons (`--history-firms`)

```powershell
.\scripts\history-firms.ps1 -Years 2023,2024,2025      # 15 Oct - 15 Nov each year, SP data
```

This downloads `VIIRS_SNPP_SP`, `VIIRS_NOAA20_SP` and `VIIRS_NOAA21_SP` for the state's bounding box in
5-day chunks, into `data\firms\history\<year>\<chunk start>\`, with one `manifest.json` per chunk.
Chunks that are already present are skipped. Use `-SeasonStart` and `-SeasonEnd` (`MM-dd`) to change
the season. Pass every CSV to `run`:

```powershell
$hist = Get-ChildItem data\firms\history -Recurse -Filter *.csv | ForEach-Object { '--history-firms'; $_.FullName }
python -m agni_pipeline run ... @hist
```

### 4.6 Cropland evidence (`--cell-evidence`)

```powershell
.\scripts\cropland.ps1 -Grid output\<a real run>\risk_grid.geojson
python -m agni_pipeline run ... --cell-evidence data\evidence\cropland_worldcover2021_5000m.csv
```

`prepare-cropland` builds the same grid as `run`, from the same boundary and `--cell-size-m`, so the
`cell_id` values match. `-Grid` / `--grid` fails if they differ from an existing risk grid. The
command does this:

- **Downloads the tiles.** It fetches the ESA WorldCover 10 m tiles (3° × 3°, EPSG:4326) that cover
  the boundary into `data\landcover\worldcover\<version>\`. The default is `v200`, the 2021 map;
  `v100` is 2020. Tiles that are already present are skipped.
- **Computes the fraction for every cell:**

  ```text
  cropland_fraction = pixels of class 40 (Cropland) / pixels with any class (value != 0)
  ```

  It counts the 10 m pixels whose centre lies inside the clipped cell. Within a 5 km cell, pixel
  area varies by less than 0.1 %. A cell with no valid pixel gets a blank value (unavailable),
  never 0.
- **Writes the outputs:** `data\evidence\cropland_worldcover<year>_<size>m.csv`
  (`cell_id,cropland_fraction`), plus `.meta.json` with the product, licence, class, method and the
  SHA-256 of every tile and of the CSV.

This is **general cropland coverage**. WorldCover does not separate paddy from other crops, so do
not present it as paddy area. ESA WorldCover is CC BY 4.0: credit "© ESA WorldCover project /
Contains modified Copernicus Sentinel data processed by ESA WorldCover consortium" wherever results
are shown.

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
| `historical_recurrence` (0.3) | `--history-firms` | mean over covered seasons of `min(count_season / 5, 1)`; unavailable if no history file |
| `cropland_fraction` (tie-break, no weight) | `--cell-evidence` column | never changes the score; orders equal scores (see below) |

- `evidence_completeness` is the sum of the weights of available score components divided by their total weight.
- `risk_score` is `round_half_up(100 × weighted mean of available components)`. Missing evidence is
  never counted as zero.
- The score is `null` / `unknown` when completeness is below `min_evidence_completeness` (0.5).
- The score is also `null` / `unknown` when a cell has **zero detections and no independent evidence**
  (in the defaults, no history; a tie-break never counts as evidence).
- Levels follow the contract thresholds: low 0–39, medium 40–69, high 70–100.

**Historical recurrence.** A *season* is the calendar year of `acq_date`: Punjab's paddy-residue season
(October–November) never crosses a year end. A season counts as *covered* when the history files
contain any valid row in it, before the quality and boundary filters. Each covered season's
detections in the cell are capped at 5, then averaged over the seasons:

| Cell's detections in 2023 / 2024 / 2025 | Component value |
| --- | ---: |
| 5+ / 5+ / 5+ (burns every season) | 1.00 |
| 200 / 0 / 0 (one very active season) | 0.33 |
| 2 / 5 / 0 | 0.47 |
| 0 / 0 / 0 | 0.00 |

So recurrence matters more than volume, and no single active season can dominate. Totals capped
across all seasons (the earlier `min(total / 20, 1)` rule) let one exceptional year saturate most
cells. A cell with zero detections in the window **and** in every covered season is scored, and
normally comes out `low`. Several seasons of coverage are evidence, but low priority still does not
prove no burning, and `metadata.interpretation` says so. The pipeline warns when a history season is
the window's own year, because that season is partial. `score_explanations.csv` lists
`historical_fire_count_by_season` and `historical_seasons_with_fire` for every cell.

The weights are expert-set defaults. They have not been fitted or validated against ground truth,
and you can tune them in the JSON config. Recent detections are the main signal (0.5) and historical
recurrence the secondary one (0.3). With the defaults, a cell with zero window detections can reach
at most 38 (low), so detected fires come first in the verification queue. A "low" score means "lower
relative priority", never "no burning".

**Cropland is a tie-break, not a score component** (`"role": "tie_break"` in the config). It never
changes `risk_score`, `risk_level` or `evidence_completeness`. Among cells with **equal scores that
have fire evidence** (a detection in the window or in any historical season), the cell with more
cropland ranks first. Cells without fire evidence get no tie-break value, so cropland alone never
raises a cell's priority. The resulting `priority_rank` (score descending, then tie-break
descending, then `cell_id`; unscored cells have no rank) is written to every scored feature in
`risk_grid.geojson` and to `score_explanations.csv`, with `tie_break_value`.
`metadata.scoring.ordering` describes the order (see §8).

The cell-evidence CSV has a `cell_id` column plus one column per `cell_attribute` component, with
values in [0, 1]. It must be prepared for the same `--cell-size-m`, because IDs encode the size.
`prepare-cropland` (§4.6) writes one for `cropland_fraction`.

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
    reconcile.py    detection funnel: where every input row went
    firms_fetch.py  NASA FIRMS Area API download + manifest
    prepare_boundaries.py  extract/reproject authoritative boundaries to WGS84
    cropland.py     ESA WorldCover class-40 fraction per cell (optional rasterio)
    cli.py          `agni-pipeline run | demo | validate | fetch-firms | prepare-boundaries | prepare-cropland`
    default_scoring.json
  fixtures/synthetic/   SYNTHETIC test inputs (not real data)
  demo/                 committed deterministic demo output (SYNTHETIC)
  scripts/real-data.ps1 one-command reproducible real-data run
  scripts/history-firms.ps1  historical SP seasons for --history-firms
  scripts/cropland.ps1  WorldCover cropland fraction for --cell-evidence
  data/, output/        real inputs and results (git-ignored, except output/real/risk_grid.geojson)
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
- **Optional `priority_rank`.** Every scored cell carries `priority_rank`, a positive integer where
  1 is verified first. The order is `risk_score` descending, then the cropland tie-break (only for
  cells with fire evidence), then `cell_id`. Cells with `risk_score: null` have no rank and omit the
  field. The rank never changes `risk_score`, `risk_level` or `evidence_completeness`. The validator
  checks that ranks are positive integers, unique, given only to scored cells, and never put a
  lower score before a higher one. To show the tie-break, sort by `priority_rank` (ascending), not
  by `risk_score` alone.

## 9. Real datasets

None of these are in the repository, and the pipeline never fabricates them.

| Dataset | Where | Used as |
| --- | --- | --- |
| NASA FIRMS VIIRS 375 m active fires (S-NPP, NOAA-20, NOAA-21) | <https://firms.modaps.eosdis.nasa.gov/api/area/>, with a free MAP_KEY | `--firms`, downloaded by `fetch-firms` |
| Punjab state and district boundaries | Survey of India data distributed by NWIC: `state_nwic_geojson.zip` and `district_nwic_geojson.zip` (EPSG:7755, `src_agency` "Survey of India (SOI)") | `--boundary` and `--districts`, after `prepare-boundaries` |
| Earlier-season detections (optional) | FIRMS archive downloads, `VIIRS_*_SP` | `--history-firms` |
| Cropland share per cell (optional) | ESA WorldCover 10 m 2021 v200, class 40 Cropland (CC BY 4.0), <https://esa-worldcover.org>; tiles from `esa-worldcover.s3.eu-central-1.amazonaws.com` | `--cell-evidence`, after `prepare-cropland` (general cropland, not paddy) |

**Known limitation of the current boundary files.** They contain **22** Punjab districts.
Malerkotla, created in 2021 as the 23rd, is absent, and its area falls under **Sangrur**.
`prepare-boundaries --expect-count 23` warns about this. Use a newer Survey of India release when one
is available, and do not draw a Malerkotla boundary by hand.

The boundary files' licence terms are set by the publisher. Check them before redistributing derived
files.
