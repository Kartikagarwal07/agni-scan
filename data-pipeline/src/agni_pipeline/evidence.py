"""Optional per-cell auxiliary evidence (e.g. cropland fraction) keyed by cell_id.

CSV layout: a ``cell_id`` column plus one column per ``cell_attribute``
component named in the scoring config. Values must be numbers in [0, 1].
Blank, ``NA``, ``NaN`` or ``null`` mean "not available for this cell" and
are never converted to zero. Rows whose ``data_label`` is ``SYNTHETIC`` mark
the file as synthetic.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from .errors import InputValidationError
from .firms import SYNTHETIC_LABEL, file_sha256

_MISSING = {"", "na", "n/a", "nan", "null", "none"}


@dataclass
class CellEvidenceTable:
    path: Path
    sha256: str
    values: dict[str, dict[str, float | None]]
    columns_used: list[str]
    synthetic: bool
    warnings: list[str] = field(default_factory=list)


def load_cell_evidence(path: str | Path, attribute_names: list[str]) -> CellEvidenceTable:
    path = Path(path)
    if not path.is_file():
        raise InputValidationError(f"cell-evidence CSV not found: {path}")
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip().lower() for h in (reader.fieldnames or [])]
        if "cell_id" not in header:
            raise InputValidationError(f"{path.name}: missing required column 'cell_id'")
        reader.fieldnames = header
        used = [a for a in attribute_names if a in header]
        warnings = []
        missing_cols = [a for a in attribute_names if a not in header]
        if missing_cols:
            warnings.append(f"{path.name}: no column for component(s) {', '.join(missing_cols)}; treated as unavailable")

        values: dict[str, dict[str, float | None]] = {}
        errors: list[str] = []
        synthetic = False
        for line_no, row in enumerate(reader, start=2):
            if (row.get("data_label") or "").strip().upper() == SYNTHETIC_LABEL:
                synthetic = True
            cell_id = (row.get("cell_id") or "").strip()
            if not cell_id:
                errors.append(f"line {line_no}: empty cell_id")
                continue
            if cell_id in values:
                errors.append(f"line {line_no}: duplicate cell_id {cell_id!r}")
                continue
            parsed: dict[str, float | None] = {}
            for name in used:
                text = (row.get(name) or "").strip()
                if text.lower() in _MISSING:
                    parsed[name] = None
                    continue
                try:
                    number = float(text)
                except ValueError:
                    errors.append(f"line {line_no}: {name} {text!r} is not a number")
                    continue
                if not math.isfinite(number) or not 0 <= number <= 1:
                    errors.append(f"line {line_no}: {name} {text!r} must be within [0, 1]")
                    continue
                parsed[name] = number
            values[cell_id] = parsed

    if errors:
        listed = "\n  - ".join(errors[:20])
        raise InputValidationError(f"{path.name}: {len(errors)} invalid row(s):\n  - {listed}")
    return CellEvidenceTable(path, file_sha256(path), values, used, synthetic, warnings)
