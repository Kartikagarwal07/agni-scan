"""Stable projected grid, clipping to the region, and detection assignment.

Grid definition
---------------
Cells are squares of ``cell_size_m`` metres in WGS 84 / UTM 43N
(EPSG:32643), aligned to the CRS origin (easting 0, northing 0). A cell's
row and column are therefore pure functions of its location and the cell
size, independent of the boundary file's extent, so cell IDs are stable
across runs and boundary revisions:

    PB-<size>M-N<row:05d>-E<col:05d>        e.g. PB-5000M-N00680-E00080

where ``row = floor(northing / size)`` and ``col = floor(easting / size)``.
If clipping to the region splits a square into several disjoint polygons
(the contract requires Polygon, not MultiPolygon, geometry), each part is
a separate cell with suffix ``-P1``, ``-P2`` ... ordered north-to-south then
west-to-east. Part suffixes can change if the boundary file changes.

Assignment
----------
Each detection is projected to EPSG:32643 and placed with half-open
intervals, ``[x0, x0 + size) x [y0, y0 + size)``: a point on a shared edge
belongs to exactly one cell (the cell to its east/north), so no detection is
double-counted. A detection is counted only if it lies inside or on the
region boundary.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon, box

from .boundary import DistrictSet, Region, project_points
from .firms import Detection

# Clipped fragments smaller than this are treated as numerical slivers.
MIN_PART_AREA_M2 = 100.0


@dataclass(frozen=True)
class GridSpec:
    cell_size_m: int
    id_prefix: str = "PB"

    def __post_init__(self):
        if not isinstance(self.cell_size_m, int) or not 100 <= self.cell_size_m <= 50_000:
            raise ValueError("cell_size_m must be an integer between 100 and 50000 metres")

    def index_of(self, x: float, y: float) -> tuple[int, int]:
        return math.floor(y / self.cell_size_m), math.floor(x / self.cell_size_m)

    def square(self, row: int, col: int) -> Polygon:
        s = self.cell_size_m
        return box(col * s, row * s, (col + 1) * s, (row + 1) * s)

    def cell_id(self, row: int, col: int, part: int | None = None) -> str:
        base = f"{self.id_prefix}-{self.cell_size_m}M-N{row:05d}-E{col:05d}"
        return base if part is None else f"{base}-P{part}"


@dataclass
class GridCell:
    cell_id: str
    row: int
    col: int
    part: int | None
    geometry_projected: Polygon
    district: str | None = None
    district_overlap: float | None = None


@dataclass
class Grid:
    spec: GridSpec
    cells: list[GridCell]
    by_index: dict[tuple[int, int], list[GridCell]] = field(default_factory=dict)
    dropped_slivers: int = 0

    def __post_init__(self):
        if not self.by_index:
            for cell in self.cells:
                self.by_index.setdefault((cell.row, cell.col), []).append(cell)


def _polygon_parts(geom) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [] if geom.is_empty else [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if not g.is_empty]
    return [p for g in getattr(geom, "geoms", []) for p in _polygon_parts(g)]


def generate_grid(region: Region, spec: GridSpec) -> Grid:
    """Create every grid cell that overlaps the region, clipped to it."""
    area = region.geometry_projected
    minx, miny, maxx, maxy = area.bounds
    r0, c0 = spec.index_of(minx, miny)
    r1, c1 = spec.index_of(maxx, maxy)
    rows, cols = np.meshgrid(np.arange(r0, r1 + 1), np.arange(c0, c1 + 1), indexing="ij")
    rows, cols = rows.ravel(), cols.ravel()
    s = spec.cell_size_m
    squares = shapely.box(cols * s, rows * s, (cols + 1) * s, (rows + 1) * s)

    shapely.prepare(area)
    hits = np.flatnonzero(shapely.intersects(area, squares))
    inside = shapely.contains_properly(area, squares[hits])
    clipped = squares[hits].copy()
    edge = hits[~inside]
    clipped[~inside] = shapely.intersection(squares[edge], area)

    cells: list[GridCell] = []
    dropped = 0
    for k, idx in enumerate(hits):
        row, col = int(rows[idx]), int(cols[idx])
        parts = [p for p in _polygon_parts(clipped[k])]
        kept = [p for p in parts if p.area >= MIN_PART_AREA_M2]
        dropped += len(parts) - len(kept)
        if not kept:
            continue
        if len(kept) == 1:
            cells.append(GridCell(spec.cell_id(row, col), row, col, None, kept[0]))
            continue
        kept.sort(key=lambda p: (-p.representative_point().y, p.representative_point().x))
        for n, part in enumerate(kept, start=1):
            cells.append(GridCell(spec.cell_id(row, col, n), row, col, n, part))

    cells.sort(key=lambda c: (-c.row, c.col, c.part or 0))
    return Grid(spec=spec, cells=cells, dropped_slivers=dropped)


@dataclass
class Assignment:
    detection: Detection
    cell_id: str | None
    status: str  # assigned | outside_region | in_dropped_sliver


@dataclass
class AssignmentResult:
    counts: Counter
    assignments: list[Assignment]

    @property
    def status_counts(self) -> Counter:
        return Counter(a.status for a in self.assignments)


def assign_detections(detections: list[Detection], grid: Grid, region: Region) -> AssignmentResult:
    """Count each detection in exactly one grid cell (or none, if outside the region)."""
    counts: Counter = Counter()
    assignments: list[Assignment] = []
    if not detections:
        return AssignmentResult(counts, assignments)

    xs, ys = project_points([d.longitude for d in detections], [d.latitude for d in detections])
    points = shapely.points(xs, ys)
    area = region.geometry_projected
    shapely.prepare(area)
    in_region = shapely.covers(area, points)

    for det, x, y, pt, ok in zip(detections, xs, ys, points, in_region):
        if not ok:
            assignments.append(Assignment(det, None, "outside_region"))
            continue
        candidates = grid.by_index.get(grid.spec.index_of(float(x), float(y)), [])
        if not candidates:
            assignments.append(Assignment(det, None, "in_dropped_sliver"))
            continue
        cell = candidates[0]
        if len(candidates) > 1:
            covering = [c for c in candidates if c.geometry_projected.covers(pt)]
            cell = covering[0] if covering else min(candidates, key=lambda c: c.geometry_projected.distance(pt))
        counts[cell.cell_id] += 1
        assignments.append(Assignment(det, cell.cell_id, "assigned"))
    return AssignmentResult(counts, assignments)


def assign_districts(grid: Grid, districts: DistrictSet) -> int:
    """Attribute each cell to the district covering the largest share of its area.

    Returns the number of cells that overlap no district. Those keep
    ``district=None``; no district is ever inferred for them.
    """
    geoms = [d.geometry_projected for d in districts.districts]
    tree = shapely.STRtree(geoms)
    unassigned = 0
    for cell in grid.cells:
        best_name, best_area = None, 0.0
        for i in tree.query(cell.geometry_projected, predicate="intersects"):
            overlap = cell.geometry_projected.intersection(geoms[i]).area
            if overlap > best_area:
                best_name, best_area = districts.districts[i].name, overlap
        if best_name is None or best_area <= 0:
            unassigned += 1
            continue
        cell.district = best_name
        cell.district_overlap = best_area / cell.geometry_projected.area
    return unassigned


def point_in_cell(grid: Grid, lon: float, lat: float) -> str | None:
    """Return the cell ID a single WGS84 point falls into (helper for tests/debugging)."""
    xs, ys = project_points([lon], [lat])
    candidates = grid.by_index.get(grid.spec.index_of(float(xs[0]), float(ys[0])), [])
    pt = Point(float(xs[0]), float(ys[0]))
    for c in candidates:
        if c.geometry_projected.covers(pt):
            return c.cell_id
    return None
