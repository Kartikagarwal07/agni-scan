"""Per-cell cropland fraction from ESA WorldCover 10 m (class 40, "Cropland").

Product: ESA WorldCover 10 m, https://esa-worldcover.org (CC BY 4.0). Tiles are
3 x 3 degree GeoTIFFs in EPSG:4326 named by their south-west corner, e.g.
``ESA_WorldCover_10m_2021_v200_N30E075_Map.tif``, served from the public bucket
https://esa-worldcover.s3.eu-central-1.amazonaws.com.

For every cell of the pipeline grid (same boundary, cell size and therefore the
same cell_id values as the risk grid):

    cropland_fraction = pixels of class 40 / pixels with any class (value != 0)

counting the 10 m pixels whose centre lies inside the cell's clipped polygon.
Pixel counts stand in for area: within a 5 km cell the pixel area varies by less
than 0.1 %. A cell with no valid pixel gets a blank value (unavailable), never 0.

Class 40 is general cropland. WorldCover does not separate paddy from other
crops, so this layer must not be described as paddy coverage.

rasterio is an optional dependency (``pip install -e ".[landcover]"``); it is
imported only when tiles are read.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .boundary import Region, to_wgs84
from .errors import PipelineError
from .firms import file_sha256
from .grid import Grid

BUCKET = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
VERSIONS = {"v200": 2021, "v100": 2020}
CROPLAND_CLASS = 40
NODATA = 0
TILE_DEG = 3
LICENCE = "CC BY 4.0"
ATTRIBUTION = "© ESA WorldCover project / Contains modified Copernicus Sentinel data processed by ESA WorldCover consortium"
LAYER_LABEL = "General cropland coverage (ESA WorldCover class 40, Cropland). Not paddy-specific."

# (url, destination) -> None. Injectable so tests never touch the network.
Downloader = Callable[[str, Path], None]


def tile_name(lat0: int, lon0: int) -> str:
    return f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d}{'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}"


def tiles_for_bounds(bounds: tuple[float, float, float, float]) -> list[str]:
    """Names of the 3-degree tiles covering (west, south, east, north)."""
    west, south, east, north = bounds
    lats = range(math.floor(south / TILE_DEG) * TILE_DEG, math.ceil(north / TILE_DEG) * TILE_DEG, TILE_DEG)
    lons = range(math.floor(west / TILE_DEG) * TILE_DEG, math.ceil(east / TILE_DEG) * TILE_DEG, TILE_DEG)
    return [tile_name(lat, lon) for lat in lats for lon in lons]


def tile_filename(name: str, version: str) -> str:
    return f"ESA_WorldCover_10m_{VERSIONS[version]}_{version}_{name}_Map.tif"


def tile_url(name: str, version: str) -> str:
    return f"{BUCKET}/{version}/{VERSIONS[version]}/map/{tile_filename(name, version)}"


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "agni-scan-pipeline"})
    with urllib.request.urlopen(request, timeout=300) as response, open(dest, "wb") as fh:
        shutil.copyfileobj(response, fh, length=1 << 20)


def ensure_tiles(
    names: list[str], tiles_dir: Path, version: str, *, download: bool = True, downloader: Downloader = _download
) -> list[Path]:
    """Local paths of the tiles in <tiles_dir>/<version>/, downloading any that are missing (via a .part file)."""
    if version not in VERSIONS:
        raise PipelineError(f"unknown WorldCover version {version!r}; choose from {sorted(VERSIONS)}")
    tiles_dir = Path(tiles_dir) / version
    tiles_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = tiles_dir / tile_filename(name, version)
        if not path.is_file():
            if not download:
                raise PipelineError(f"WorldCover tile missing: {path} (run without --no-download to fetch it)")
            part = path.with_name(path.name + ".part")
            try:
                downloader(tile_url(name, version), part)
            except OSError as exc:
                part.unlink(missing_ok=True)
                raise PipelineError(f"could not download {tile_url(name, version)} ({exc})") from None
            part.replace(path)
        paths.append(path)
    return paths


@dataclass
class CellCover:
    cell_id: str
    cropland_pixels: int = 0
    valid_pixels: int = 0

    @property
    def fraction(self) -> float | None:
        return None if self.valid_pixels == 0 else self.cropland_pixels / self.valid_pixels


def cropland_cover(grid: Grid, tile_paths: list[Path]) -> list[CellCover]:
    """Count class-40 and valid pixels per grid cell across all tiles."""
    try:
        import numpy as np
        import rasterio
        from rasterio.features import geometry_mask
        from rasterio.windows import Window
    except ImportError:
        raise PipelineError('rasterio is required for cropland preparation: pip install -e ".[landcover]"') from None

    cells = [(c.cell_id, to_wgs84(c.geometry_projected)) for c in grid.cells]
    cover = {cid: CellCover(cid) for cid, _ in cells}
    for path in tile_paths:
        with rasterio.open(path) as src:
            if src.crs is None or src.crs.to_epsg() != 4326:
                raise PipelineError(f"{path.name}: expected EPSG:4326, got {src.crs}")
            t = src.transform
            if t.b or t.d or t.e >= 0:
                raise PipelineError(f"{path.name}: expected a north-up raster without rotation")
            for cid, geom in cells:
                w, s, e, n = geom.bounds
                # Pixel window covering the cell's bounds (outward-rounded), clipped to the tile.
                col0 = max(math.floor((w - t.c) / t.a), 0)
                col1 = min(math.ceil((e - t.c) / t.a), src.width)
                row0 = max(math.floor((n - t.f) / t.e), 0)
                row1 = min(math.ceil((s - t.f) / t.e), src.height)
                if col0 >= col1 or row0 >= row1:
                    continue
                window = Window(col0, row0, col1 - col0, row1 - row0)
                data = src.read(1, window=window)
                inside = geometry_mask([geom], out_shape=data.shape, transform=src.window_transform(window), invert=True)
                cover[cid].cropland_pixels += int(np.count_nonzero(inside & (data == CROPLAND_CLASS)))
                cover[cid].valid_pixels += int(np.count_nonzero(inside & (data != NODATA)))
    return [cover[cid] for cid, _ in cells]


def write_cropland_csv(path: Path, cover: list[CellCover]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["cell_id", "cropland_fraction"])
        for c in cover:
            writer.writerow([c.cell_id, "" if c.fraction is None else f"{c.fraction:.4f}"])


@dataclass
class PreparedCropland:
    csv_path: Path
    metadata_path: Path
    cover: list[CellCover]
    tiles: list[Path]


def prepare_cropland(
    *,
    region: Region,
    grid: Grid,
    output: Path,
    tiles_dir: Path,
    version: str = "v200",
    download: bool = True,
    downloader: Downloader = _download,
    now: dt.datetime | None = None,
) -> PreparedCropland:
    """Write <output> (cell_id,cropland_fraction) and <output>.meta.json describing its provenance."""
    names = tiles_for_bounds(region.geometry_wgs84.bounds)
    tiles = ensure_tiles(names, tiles_dir, version, download=download, downloader=downloader)
    cover = cropland_cover(grid, tiles)
    output = Path(output)
    write_cropland_csv(output, cover)

    now = now or dt.datetime.now(dt.timezone.utc)
    meta_path = output.with_name(output.name + ".meta.json")
    meta = {
        "layer": "cropland_fraction",
        "label": LAYER_LABEL,
        "prepared_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "product": f"ESA WorldCover 10 m {VERSIONS[version]} {version}",
        "product_year": VERSIONS[version],
        "source": "https://esa-worldcover.org",
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "class_used": {"value": CROPLAND_CLASS, "name": "Cropland"},
        "method": "class-40 pixels / pixels with any class (value != 0), counting 10 m pixels whose centre lies "
        "inside the clipped grid cell; blank when a cell has no valid pixel",
        "grid": {"cell_size_m": grid.spec.cell_size_m, "cell_count": len(grid.cells),
                 "boundary": region.source.name, "boundary_sha256": region.sha256},
        "tiles": [{"file": p.name, "url": tile_url(n, version), "sha256": file_sha256(p), "bytes": p.stat().st_size}
                  for n, p in zip(names, tiles)],
        "output_sha256": file_sha256(output),
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return PreparedCropland(output, meta_path, cover, tiles)
