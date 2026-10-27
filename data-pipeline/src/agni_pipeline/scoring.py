"""Explainable, configurable verification-priority heuristic.

For each cell, every configured evidence component yields a value in [0, 1]
or is *unavailable*:

* ``firms_window``  - detections in the analysis window,
  ``min(count / saturation_count, 1)``. Always available (a FIRMS file is a
  required input).
* ``firms_history`` - recurrence across earlier seasons. Each season's
  detections are capped separately, ``min(count_s / season_saturation_count, 1)``,
  and the component is the mean over the seasons the historical files cover.
  A cell that burns every season therefore outranks one with a single very
  active season, and no one season can dominate. Unavailable when no
  historical file (or no season before the window) is supplied.
* ``cell_attribute`` - a per-cell value in [0, 1] from the cell-evidence CSV.
  Unavailable when the CSV, the column, or the cell's value is missing.

Each component has a ``role``. ``score`` components (the default) have a
weight and make up the score. A ``tie_break`` component (at most one, a
``cell_attribute`` such as cropland_fraction) never changes ``risk_score``,
``risk_level`` or ``evidence_completeness``: it only orders cells with equal
scores, and only cells with fire evidence (a detection in the window or in any
historical season). Cells without fire evidence get no tie-break value, so
land cover alone can never raise a cell's priority.

``evidence_completeness`` is the share of total score weight whose
component is available. The score is the weighted mean of the *available*
components scaled to 0-100 and rounded half-up to an integer. Missing
evidence is never treated as zero.

The score is ``null`` (``risk_level = "unknown"``) when:

1. ``evidence_completeness`` is below ``min_evidence_completeness``; or
2. the cell has zero observed detections and no component independent of the
   analysis-window detections is available (when
   ``zero_detection_requires_independent_evidence`` is true). A missed
   detection can result from cloud, smoke, overpass timing or small or brief
   fires, so zero detections on their own are not evidence of no burning.

Risk-level thresholds are fixed by DATA_CONTRACT.md: low 0-39,
medium 40-69, high 70-100.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .errors import ConfigError
from .firms import CONFIDENCE_LEVELS, FIRE_TYPES

SOURCES = ("firms_window", "firms_history", "cell_attribute")
ROLES = ("score", "tie_break")
MEDIUM_THRESHOLD = 40
HIGH_THRESHOLD = 70


@dataclass(frozen=True)
class Component:
    name: str
    source: str
    weight: float
    saturation_count: int | None = None
    season_saturation_count: int | None = None
    description: str = ""
    role: str = "score"


@dataclass(frozen=True)
class ScoringConfig:
    components: tuple[Component, ...]
    min_evidence_completeness: float
    zero_detection_requires_independent_evidence: bool
    min_confidence: str | None
    exclude_fire_types: tuple[int, ...]
    source: str = "built-in default"

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.components if c.role == "score")

    @property
    def tie_break(self) -> Component | None:
        return next((c for c in self.components if c.role == "tie_break"), None)

    def attribute_names(self) -> list[str]:
        return [c.name for c in self.components if c.source == "cell_attribute"]

    def to_metadata(self) -> dict:
        return {
            "config_source": self.source,
            "min_evidence_completeness": self.min_evidence_completeness,
            "zero_detection_requires_independent_evidence": self.zero_detection_requires_independent_evidence,
            "firms_min_confidence": self.min_confidence,
            "firms_excluded_fire_types": list(self.exclude_fire_types),
            "risk_level_thresholds": {"low": "0-39", "medium": "40-69", "high": "70-100", "unknown": "risk_score is null"},
            "components": [
                {
                    "name": c.name,
                    "source": c.source,
                    "role": c.role,
                    "weight": c.weight if c.role == "score" else None,
                    **({"saturation_count": c.saturation_count} if c.saturation_count else {}),
                    **({"season_saturation_count": c.season_saturation_count} if c.season_saturation_count else {}),
                    "description": c.description,
                }
                for c in self.components
            ],
            "ordering": (
                "risk_score descending; equal scores among cells with fire evidence ordered by "
                f"{self.tie_break.name} descending; then cell_id. Written as priority_rank (1 = first) "
                "on every scored feature."
                if self.tie_break
                else "risk_score descending, then cell_id"
            ),
        }


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ConfigError(f"scoring config: {message}")


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def parse_config(data: dict, source: str) -> ScoringConfig:
    _require(isinstance(data, dict), "top level must be a JSON object")
    raw_components = data.get("components")
    _require(isinstance(raw_components, list) and raw_components, "'components' must be a non-empty list")

    components: list[Component] = []
    for i, c in enumerate(raw_components):
        _require(isinstance(c, dict), f"component {i} must be an object")
        name, src, weight = c.get("name"), c.get("source"), c.get("weight")
        role = c.get("role", "score")
        _require(isinstance(name, str) and name.isidentifier(), f"component {i}: 'name' must be an identifier")
        _require(src in SOURCES, f"component {name!r}: 'source' must be one of {SOURCES}")
        _require(role in ROLES, f"component {name!r}: 'role' must be one of {ROLES}")
        if role == "tie_break":
            _require(src == "cell_attribute", f"component {name!r}: a tie_break component must be a cell_attribute")
            _require(weight is None, f"component {name!r}: a tie_break component has no weight (it never changes the score)")
            weight = 0.0
        else:
            _require(
                isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight > 0
                and math.isfinite(weight),
                f"component {name!r}: 'weight' must be a positive number",
            )
        sat, season_sat = c.get("saturation_count"), c.get("season_saturation_count")
        if src == "firms_window":
            _require(_positive_int(sat), f"component {name!r}: 'saturation_count' must be an integer >= 1")
            _require(season_sat is None, f"component {name!r}: 'season_saturation_count' only applies to firms_history")
        elif src == "firms_history":
            _require(
                sat is None,
                f"component {name!r}: firms_history is scored per season; use 'season_saturation_count' "
                "instead of 'saturation_count'",
            )
            _require(_positive_int(season_sat), f"component {name!r}: 'season_saturation_count' must be an integer >= 1")
        else:
            _require(sat is None and season_sat is None,
                     f"component {name!r}: 'saturation_count' only applies to FIRMS sources")
        components.append(Component(name, src, float(weight), sat, season_sat, str(c.get("description", "")), role))

    names = [c.name for c in components]
    _require(len(set(names)) == len(names), "component names must be unique")
    for src in ("firms_window", "firms_history"):
        _require(sum(c.source == src for c in components) <= 1, f"at most one {src!r} component is allowed")
    _require(sum(c.role == "tie_break" for c in components) <= 1, "at most one tie_break component is allowed")
    _require(any(c.role == "score" for c in components), "at least one component must have role 'score'")

    mec = data.get("min_evidence_completeness", 0.5)
    _require(
        isinstance(mec, (int, float)) and not isinstance(mec, bool) and 0 < mec <= 1,
        "'min_evidence_completeness' must be in (0, 1]",
    )
    zero_rule = data.get("zero_detection_requires_independent_evidence", True)
    _require(isinstance(zero_rule, bool), "'zero_detection_requires_independent_evidence' must be true or false")

    filters = data.get("firms_filters", {})
    _require(isinstance(filters, dict), "'firms_filters' must be an object")
    min_conf = filters.get("min_confidence", "nominal")
    _require(min_conf is None or min_conf in CONFIDENCE_LEVELS, f"'min_confidence' must be null or one of {CONFIDENCE_LEVELS}")
    excl = filters.get("exclude_fire_types", [1, 2, 3])
    _require(
        isinstance(excl, list) and all(isinstance(t, int) and t in FIRE_TYPES for t in excl),
        f"'exclude_fire_types' must be a list drawn from {sorted(FIRE_TYPES)}",
    )

    return ScoringConfig(
        components=tuple(components),
        min_evidence_completeness=float(mec),
        zero_detection_requires_independent_evidence=zero_rule,
        min_confidence=min_conf,
        exclude_fire_types=tuple(excl),
        source=source,
    )


def load_config(path: str | Path | None = None) -> ScoringConfig:
    if path is None:
        text = resources.files("agni_pipeline").joinpath("default_scoring.json").read_text(encoding="utf-8")
        return parse_config(json.loads(text), "built-in default (agni_pipeline/default_scoring.json)")
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"scoring config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name}: not valid JSON ({exc})") from None
    return parse_config(data, str(path.name))


@dataclass
class CellEvidence:
    observed_count: int
    # Detections per historical season, one entry for every season covered (zeros
    # included). None or empty: no historical evidence supplied.
    history_season_counts: tuple[int, ...] | None
    attributes: dict[str, float | None]


@dataclass
class ComponentResult:
    name: str
    available: bool
    value: float | None
    weight: float
    role: str = "score"


@dataclass
class ScoreResult:
    risk_score: int | None
    risk_level: str
    evidence_completeness: float
    components: list[ComponentResult]
    reason: str
    # Value of the tie_break component; None when there is none, the cell has no
    # fire evidence, the value is missing, or the cell is unscored.
    tie_break: float | None = None


def risk_level_for(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _saturate(count: int, saturation: int) -> float:
    return min(count / saturation, 1.0)


def score_cell(evidence: CellEvidence, config: ScoringConfig) -> ScoreResult:
    results: list[ComponentResult] = []
    for c in config.components:
        if c.source == "firms_window":
            value = _saturate(evidence.observed_count, c.saturation_count)
        elif c.source == "firms_history":
            counts = evidence.history_season_counts
            value = (
                sum(_saturate(n, c.season_saturation_count) for n in counts) / len(counts) if counts else None
            )
        else:
            value = evidence.attributes.get(c.name)
        results.append(ComponentResult(c.name, value is not None, value, c.weight, c.role))

    available = [r for r in results if r.available and r.role == "score"]
    completeness = round(sum(r.weight for r in available) / config.total_weight, 4)

    if completeness < config.min_evidence_completeness:
        return ScoreResult(None, "unknown", completeness, results, "insufficient_evidence")

    if config.zero_detection_requires_independent_evidence and evidence.observed_count == 0:
        window_names = {c.name for c in config.components if c.source == "firms_window"}
        if not any(r.name not in window_names for r in available):
            return ScoreResult(None, "unknown", completeness, results, "zero_detections_without_independent_evidence")

    weighted = sum(r.weight * r.value for r in available) / sum(r.weight for r in available)
    # Snap away binary noise (0.695 * 100 == 69.4999...) before rounding half-up.
    score = min(100, max(0, math.floor(round(weighted * 100, 9) + 0.5)))
    has_fire = evidence.observed_count > 0 or any(evidence.history_season_counts or ())
    tie = next((r.value for r in results if r.role == "tie_break"), None) if has_fire else None
    return ScoreResult(score, risk_level_for(score), completeness, results, "scored", tie)
