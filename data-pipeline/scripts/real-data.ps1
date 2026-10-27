<#
.SYNOPSIS
  Reproducible real-data run: authoritative boundaries -> NASA FIRMS VIIRS -> risk grid.

.DESCRIPTION
  1. prepare-boundaries: extracts Punjab (stcode 03) from the Survey of India / NWIC
     state and district zips and reprojects them to WGS84 (skipped if already done,
     unless -Force).
  2. fetch-firms: downloads the three VIIRS NRT sources for the Punjab bounding box
     into data\firms\<UTC timestamp>\ with a manifest.json (SHA-256 per file).
     Skipped when -FirmsDir points at an earlier fetch, which reproduces that run.
  3. run: builds the grid for exactly the fetched dates and writes
     output\real-<end date>-<fetch timestamp>\ (risk_grid.geojson, detection_funnel.csv, ...).

  Needs FIRMS_MAP_KEY in the environment or in the repository's .env.local.
  data\ and output\ are git-ignored: real inputs and results stay on this machine.

.EXAMPLE
  .\scripts\real-data.ps1 -StateZip $HOME\Downloads\state_nwic_geojson.zip -DistrictZip $HOME\Downloads\district_nwic_geojson.zip

.EXAMPLE
  # Fixed dates (UTC acq_date 2026-10-23 .. 2026-10-26)
  .\scripts\real-data.ps1 -StateZip ... -DistrictZip ... -StartDate 2026-10-23 -Days 4

.EXAMPLE
  # Re-run on an earlier download without contacting FIRMS
  .\scripts\real-data.ps1 -StateZip ... -DistrictZip ... -FirmsDir data\firms\20261027-061500
#>
param(
  [Parameter(Mandatory)] [string] $StateZip,
  [Parameter(Mandatory)] [string] $DistrictZip,
  [string] $StartDate,
  [ValidateRange(1, 5)] [int] $Days = 5,
  [string] $FirmsDir,
  [int] $CellSizeM = 5000,
  [switch] $Force
)

$ErrorActionPreference = 'Stop'
$pipelineRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $pipelineRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python environment not found at $python. Follow the setup steps in data-pipeline\README.md first." }

# Resolve user-supplied paths before changing directory.
$StateZip = (Resolve-Path $StateZip).Path
$DistrictZip = (Resolve-Path $DistrictZip).Path
if ($FirmsDir) { $FirmsDir = (Resolve-Path $FirmsDir).Path }

function Invoke-Pipeline([string[]] $Arguments) {
  & $python -m agni_pipeline @Arguments
  if ($LASTEXITCODE -ne 0) { throw "agni-pipeline $($Arguments[0]) failed (exit code $LASTEXITCODE)" }
}

Push-Location $pipelineRoot
try {
  $state = 'data\boundaries\punjab_state.geojson'
  $districts = 'data\boundaries\punjab_districts.geojson'

  Write-Host '== 1/3 Boundaries (Survey of India via NWIC)'
  if ($Force -or -not (Test-Path $state)) {
    Invoke-Pipeline @('prepare-boundaries', $StateZip, '--output', $state, '--kind', 'state', '--value', '03')
  } else { Write-Host "  using existing $state (pass -Force to rebuild)" }
  if ($Force -or -not (Test-Path $districts)) {
    Invoke-Pipeline @('prepare-boundaries', $DistrictZip, '--output', $districts, '--kind', 'districts', '--value', '03',
                      '--expect-count', '23', '--state', $state)
  } else { Write-Host "  using existing $districts (pass -Force to rebuild)" }

  Write-Host '== 2/3 NASA FIRMS VIIRS detections'
  if (-not $FirmsDir) {
    $FirmsDir = Join-Path 'data\firms' ((Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss'))
    $fetch = @('fetch-firms', '--output-dir', $FirmsDir, '--boundary', $state, '--days', "$Days")
    if ($StartDate) { $fetch += @('--start-date', $StartDate) }
    Invoke-Pipeline $fetch
  } else { Write-Host "  reusing $FirmsDir" }

  $manifest = Get-Content (Join-Path $FirmsDir 'manifest.json') -Raw | ConvertFrom-Json
  $endDate = $manifest.acq_date_range[1]
  # One output folder per fetch, so re-runs never overwrite an earlier result.
  $outputDir = "output\real-$endDate-$(Split-Path $FirmsDir -Leaf)"
  $runArgs = @('run', '--boundary', $state, '--districts', $districts,
               '--analysis-date', $endDate, '--window-days', "$($manifest.day_range)",
               '--cell-size-m', "$CellSizeM", '--output-dir', $outputDir)
  foreach ($file in $manifest.files) { $runArgs += @('--firms', (Join-Path $FirmsDir $file.file)) }

  Write-Host "== 3/3 Risk grid for $($manifest.acq_date_range[0]) .. $endDate (UTC)"
  Invoke-Pipeline $runArgs
  Write-Host "Done. Inputs: $FirmsDir  Output: $outputDir"
}
finally {
  Pop-Location
}
