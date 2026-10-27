"""Detection funnel: where every input row went, per FIRMS file.

For each file the counts satisfy two identities, which are checked on every run:

    rows_read = rejected_invalid + valid
    valid     = duplicates + removed_fire_type + removed_low_confidence
              + removed_missing_confidence + outside_window
              + outside_region + in_dropped_sliver + assigned

so a reported number can always be traced back to the raw files.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field

from .errors import PipelineError
from .firms import Detection, FirmsLoadResult, quality_reason
from .grid import Assignment

STAGES = (
    "rows_read",
    "rejected_invalid",
    "valid",
    "duplicates",
    "removed_fire_type",
    "removed_low_confidence",
    "removed_missing_confidence",
    "outside_window",
    "outside_region",
    "in_dropped_sliver",
    "assigned",
)
_VALID_PARTS = STAGES[3:]


@dataclass
class FunnelRow:
    source_file: str
    counts: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {"source_file": self.source_file, **{s: self.counts.get(s, 0) for s in STAGES}}


def _quality_stage(reason: str) -> str:
    if reason.startswith("type_"):
        return "removed_fire_type"
    if reason == "confidence_missing":
        return "removed_missing_confidence"
    return "removed_low_confidence"


def detection_funnel(
    results: list[FirmsLoadResult],
    unique: list[Detection],
    *,
    min_confidence: str | None,
    exclude_fire_types: tuple[int, ...],
    window: tuple[dt.date, dt.date],
    assignments: list[Assignment],
) -> list[FunnelRow]:
    """Per-file funnel plus a final TOTAL row. Raises AssertionError if counts do not balance."""
    unique_ids = {id(d) for d in unique}
    status = {id(a.detection): a.status for a in assignments}
    start, end = window
    rows: list[FunnelRow] = []
    for res in results:
        row = FunnelRow(res.path.name)
        c = row.counts
        c["rows_read"] = res.total_rows
        c["rejected_invalid"] = len(res.rejections)
        c["valid"] = len(res.detections)
        for d in res.detections:
            if id(d) not in unique_ids:
                c["duplicates"] += 1
                continue
            reason = quality_reason(d, min_confidence=min_confidence, exclude_fire_types=exclude_fire_types)
            if reason is not None:
                c[_quality_stage(reason)] += 1
            elif not start <= d.acq_date <= end:
                c["outside_window"] += 1
            else:
                c[status.get(id(d), "missing")] += 1
        rows.append(row)

    total = FunnelRow("TOTAL")
    for row in rows:
        total.counts.update(row.counts)
    rows.append(total)

    for row in rows:
        c = row.counts
        problems = []
        if c["missing"]:
            problems.append(f"{c['missing']} in-window detection(s) were never assigned")
        if c["rows_read"] != c["rejected_invalid"] + c["valid"]:
            problems.append("rows_read != rejected_invalid + valid")
        if c["valid"] != sum(c[s] for s in _VALID_PARTS):
            problems.append("valid != sum of downstream stages")
        if problems:
            raise PipelineError(f"detection funnel does not balance for {row.source_file}: {'; '.join(problems)}")
    return rows


def format_funnel(rows: list[FunnelRow]) -> str:
    """Fixed-width table for the CLI."""
    headers = ("file",) + STAGES
    data = [[r.source_file] + [str(r.counts.get(s, 0)) for s in STAGES] for r in rows]
    widths = [max(len(h), *(len(d[i]) for d in data)) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(cells, widths)))
    return "\n".join([line(headers)] + [line(d) for d in data])
