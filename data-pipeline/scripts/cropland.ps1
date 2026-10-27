<#
.SYNOPSIS
  Per-cell cropland fraction from ESA WorldCover 10 m (class 40), for --cell-evidence.

.DESCRIPTION
  Downloads the ESA WorldCover tiles covering the Punjab boundary (skipped when present) into
  data\landcover\worldcover\<version>\ and writes data\evidence\cropland_<year>_<cell size>m.csv
  (cell_id,cropland_fraction) plus a .meta.json recording the product, licence, class, method
  and the SHA-256 of every tile and of the CSV.

  The layer is GENERAL cropland coverage (WorldCover class 40). WorldCover does not separate
  paddy from other crops.

  Needs the state boundary from real-data.ps1 (data\boundaries\punjab_state.geojson) and the
  optional raster dependency: .venv\Scripts\python.exe -m pip install -e ".[landcover]"
  data\ is git-ignored: tiles and the CSV stay on this machine.

.EXAMPLE
  .\scripts\cropland.ps1 -Grid output\real-2026-10-26-20261027-060500\risk_grid.geojson
#>
param(
  [ValidateSet('v200', 'v100')] [string] $Version = 'v200',
  [int] $CellSizeM = 5000,
  # Optional risk_grid.geojson whose cell_id values must match exactly.
  [string] $Grid
)

$ErrorActionPreference = 'Stop'
$pipelineRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $pipelineRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python environment not found at $python. Follow the setup steps in data-pipeline\README.md first." }
if ($Grid) { $Grid = (Resolve-Path $Grid).Path }

Push-Location $pipelineRoot
try {
  $state = 'data\boundaries\punjab_state.geojson'
  if (-not (Test-Path $state)) { throw "$state not found. Run scripts\real-data.ps1 (or prepare-boundaries) first." }
  $year = @{ v200 = 2021; v100 = 2020 }[$Version]
  $output = "data\evidence\cropland_worldcover${year}_${CellSizeM}m.csv"
  $cmd = @('-m', 'agni_pipeline', 'prepare-cropland', '--boundary', $state, '--cell-size-m', "$CellSizeM",
            '--version', $Version, '--output', $output)
  if ($Grid) { $cmd += @('--grid', $Grid) }
  & $python @cmd
  if ($LASTEXITCODE -ne 0) { throw "prepare-cropland failed (exit code $LASTEXITCODE)" }
}
finally {
  Pop-Location
}
