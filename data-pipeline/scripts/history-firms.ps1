<#
.SYNOPSIS
  Download historical standard-processing (SP) NASA FIRMS VIIRS detections for the
  crop-residue-burning season, for use as --history-firms.

.DESCRIPTION
  For each year, fetches VIIRS_SNPP_SP, VIIRS_NOAA20_SP and VIIRS_NOAA21_SP for the
  Punjab bounding box from -SeasonStart to -SeasonEnd (inclusive). The FIRMS Area API
  returns at most 5 days per request, so each season is split into 5-day chunks:
    data\firms\history\<year>\<chunk start>\<SOURCE>.csv + manifest.json (SHA-256 per file)
  Chunks that already have a manifest.json are skipped (pass -Force to re-download).

  Filtering is NOT done here: the pipeline applies the confidence filter, de-duplication,
  the Punjab boundary and the "strictly before the analysis window" rule to --history-firms.

  Needs FIRMS_MAP_KEY in the environment or in the repository's .env.local, and the state
  boundary from real-data.ps1 (data\boundaries\punjab_state.geojson).
  data\ is git-ignored: the raw files stay on this machine.

.EXAMPLE
  .\scripts\history-firms.ps1 -Years 2023,2024,2025
#>
param(
  [Parameter(Mandatory)] [int[]] $Years,
  [string] $SeasonStart = '10-15',
  [string] $SeasonEnd = '11-15',
  [switch] $Force
)

$ErrorActionPreference = 'Stop'
$pipelineRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $pipelineRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python environment not found at $python. Follow the setup steps in data-pipeline\README.md first." }

Push-Location $pipelineRoot
try {
  $state = 'data\boundaries\punjab_state.geojson'
  if (-not (Test-Path $state)) { throw "$state not found. Run scripts\real-data.ps1 (or prepare-boundaries) first." }
  $sources = @('VIIRS_SNPP_SP', 'VIIRS_NOAA20_SP', 'VIIRS_NOAA21_SP')

  foreach ($year in $Years) {
    $day = [datetime]::ParseExact("$year-$SeasonStart", 'yyyy-MM-dd', $null)
    $last = [datetime]::ParseExact("$year-$SeasonEnd", 'yyyy-MM-dd', $null)
    Write-Host "== $year season $($day.ToString('yyyy-MM-dd')) .. $($last.ToString('yyyy-MM-dd'))"
    while ($day -le $last) {
      $days = [math]::Min(5, ($last - $day).Days + 1)
      $dir = Join-Path "data\firms\history\$year" $day.ToString('yyyy-MM-dd')
      if (-not $Force -and (Test-Path (Join-Path $dir 'manifest.json'))) {
        Write-Host "  $dir already fetched"
      } else {
        $fetch = @('-m', 'agni_pipeline', 'fetch-firms', '--output-dir', $dir, '--boundary', $state,
                   '--days', "$days", '--start-date', $day.ToString('yyyy-MM-dd'))
        foreach ($s in $sources) { $fetch += @('--source', $s) }
        & $python @fetch
        if ($LASTEXITCODE -ne 0) { throw "fetch-firms failed for $dir (exit code $LASTEXITCODE)" }
      }
      $day = $day.AddDays($days)
    }
  }
}
finally {
  Pop-Location
}
