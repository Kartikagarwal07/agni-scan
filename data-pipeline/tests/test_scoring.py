import json

import pytest

from agni_pipeline.errors import ConfigError
from agni_pipeline.scoring import CellEvidence, load_config, parse_config, risk_level_for, score_cell


@pytest.fixture
def config():
    return load_config()


def test_default_config_loads(config):
    assert [c.name for c in config.components] == ["observed_detections", "historical_recurrence", "cropland_fraction"]
    assert config.total_weight == pytest.approx(0.8)  # cropland_fraction is a tie-break, not weighted
    assert config.tie_break.name == "cropland_fraction"
    assert config.min_confidence == "nominal"


@pytest.mark.parametrize(
    "score, level",
    [(None, "unknown"), (0, "low"), (39, "low"), (40, "medium"), (69, "medium"), (70, "high"), (100, "high")],
)
def test_contract_thresholds(score, level):
    assert risk_level_for(score) == level


def test_zero_detections_alone_are_not_evidence_of_no_burning(config):
    res = score_cell(CellEvidence(observed_count=0, history_season_counts=None, attributes={}), config)
    assert res.risk_score is None
    assert res.risk_level == "unknown"
    assert res.reason == "zero_detections_without_independent_evidence"
    assert res.evidence_completeness == 0.625


def test_detections_only_is_scored_when_completeness_suffices(config):
    res = score_cell(CellEvidence(observed_count=5, history_season_counts=None, attributes={}), config)
    assert res.risk_score == 100 and res.risk_level == "high"
    res = score_cell(CellEvidence(observed_count=1, history_season_counts=None, attributes={}), config)
    assert res.risk_score == 20 and res.risk_level == "low"


def test_zero_detections_with_independent_evidence_is_scored(config):
    res = score_cell(CellEvidence(0, (5, 5, 5), {"cropland_fraction": 1.0}), config)
    assert res.risk_score == 38  # (0.5*0 + 0.3*1) / 0.8; cropland adds nothing
    assert res.risk_level == "low"
    assert res.evidence_completeness == 1.0
    assert res.tie_break == 1.0


def test_missing_evidence_is_not_treated_as_zero(config):
    without_history = score_cell(CellEvidence(5, None, {}), config)
    # Only the window is available: 0.5*1 / 0.5 = 100; treating the missing history as zero would give 63.
    assert without_history.risk_score == 100
    assert without_history.evidence_completeness == 0.625
    assert [c.available for c in without_history.components] == [True, False, False]


def test_insufficient_completeness_gives_null():
    cfg = parse_config(
        {
            "min_evidence_completeness": 0.6,
            "components": [
                {"name": "obs", "source": "firms_window", "weight": 1, "saturation_count": 2},
                {"name": "crop", "source": "cell_attribute", "weight": 1},
            ],
        },
        "test",
    )
    res = score_cell(CellEvidence(3, None, {}), cfg)
    assert res.risk_score is None and res.reason == "insufficient_evidence"
    assert res.evidence_completeness == 0.5
    res = score_cell(CellEvidence(3, None, {"crop": 0.0}), cfg)
    assert res.risk_score == 50


def test_zero_detection_rule_can_be_disabled():
    cfg = parse_config(
        {
            "zero_detection_requires_independent_evidence": False,
            "components": [{"name": "obs", "source": "firms_window", "weight": 1, "saturation_count": 2}],
        },
        "test",
    )
    assert score_cell(CellEvidence(0, None, {}), cfg).risk_score == 0


def test_rounding_is_half_up():
    cfg = parse_config(
        {
            "zero_detection_requires_independent_evidence": False,
            "components": [{"name": "obs", "source": "firms_window", "weight": 1, "saturation_count": 200}],
        },
        "test",
    )
    assert score_cell(CellEvidence(79, None, {}), cfg).risk_score == 40  # 39.5 -> 40 (medium)
    assert score_cell(CellEvidence(139, None, {}), cfg).risk_score == 70  # 69.5 -> 70 (high)


def test_saturation_caps_component(config):
    res = score_cell(CellEvidence(50, (500, 500), {"cropland_fraction": 1.0}), config)
    assert res.risk_score == 100
    assert all(c.value <= 1 for c in res.components)


def test_history_rewards_recurrence_not_one_active_season(config):
    every_season = score_cell(CellEvidence(0, (5, 5, 5), {}), config).components[1]
    one_big_season = score_cell(CellEvidence(0, (500, 0, 0), {}), config).components[1]
    assert every_season.value == 1.0
    assert one_big_season.value == pytest.approx(1 / 3)  # a single season is capped, then averaged
    partial = score_cell(CellEvidence(0, (2, 5, 0), {}), config).components[1]
    assert partial.value == pytest.approx((0.4 + 1 + 0) / 3)


def test_zero_recent_and_zero_historical_detections_score_low(config):
    """Covered seasons with no detections are evidence: the cell is low priority, not unknown."""
    res = score_cell(CellEvidence(0, (0, 0, 0), {"cropland_fraction": 1.0}), config)
    assert res.risk_score == 0 and res.risk_level == "low" and res.reason == "scored"
    assert res.evidence_completeness == 1.0
    assert res.tie_break is None  # no fire evidence: cropland is not used at all


def test_cropland_never_changes_score_or_level(config):
    for observed, history in [(0, (5, 0, 0)), (1, (0, 0, 0)), (3, (2, 5, 1)), (6, (5, 5, 5))]:
        results = [score_cell(CellEvidence(observed, history, {"cropland_fraction": f}), config)
                   for f in (0.0, 0.5, 1.0, None)]
        assert len({(r.risk_score, r.risk_level, r.evidence_completeness) for r in results}) == 1
        assert [r.tie_break for r in results] == [0.0, 0.5, 1.0, None]


def test_cropland_alone_cannot_make_a_cell_scored(config):
    """Without history, zero detections stay unknown even with cropland: land cover is not fire evidence."""
    res = score_cell(CellEvidence(0, None, {"cropland_fraction": 1.0}), config)
    assert res.risk_level == "unknown" and res.tie_break is None


def test_empty_history_is_unavailable(config):
    res = score_cell(CellEvidence(0, (), {}), config)
    assert res.risk_level == "unknown" and res.components[1].available is False


@pytest.mark.parametrize(
    "components, message",
    [
        ([], "non-empty list"),
        ([{"name": "a", "source": "satellite", "weight": 1}], "'source' must be one of"),
        ([{"name": "a", "source": "cell_attribute", "weight": -1}], "positive number"),
        ([{"name": "a", "source": "cell_attribute", "weight": True}], "positive number"),
        ([{"name": "a", "source": "firms_window", "weight": 1}], "saturation_count"),
        ([{"name": "a", "source": "cell_attribute", "weight": 1, "saturation_count": 3}], "only applies"),
        ([{"name": "a", "source": "firms_history", "weight": 1, "saturation_count": 20}], "scored per season"),
        ([{"name": "a", "source": "firms_history", "weight": 1}], "season_saturation_count"),
        ([{"name": "a", "source": "firms_window", "weight": 1, "saturation_count": 1, "season_saturation_count": 1}],
         "only applies to firms_history"),
        ([{"name": "a", "source": "cell_attribute", "weight": 1}] * 2, "unique"),
        ([{"name": "a", "source": "cell_attribute", "weight": 1, "role": "bonus"}], "'role' must be one of"),
        ([{"name": "a", "source": "cell_attribute", "role": "tie_break"}], "at least one component"),
        ([{"name": "o", "source": "firms_window", "weight": 1, "saturation_count": 1},
          {"name": "a", "source": "cell_attribute", "weight": 1, "role": "tie_break"}], "has no weight"),
        ([{"name": "o", "source": "firms_window", "role": "tie_break", "saturation_count": 1}],
         "must be a cell_attribute"),
        ([{"name": "o", "source": "firms_window", "weight": 1, "saturation_count": 1},
          {"name": "a", "source": "cell_attribute", "role": "tie_break"},
          {"name": "b", "source": "cell_attribute", "role": "tie_break"}], "at most one tie_break"),
        ([{"name": "bad name", "source": "cell_attribute", "weight": 1}], "identifier"),
        (
            [
                {"name": "a", "source": "firms_window", "weight": 1, "saturation_count": 1},
                {"name": "b", "source": "firms_window", "weight": 1, "saturation_count": 1},
            ],
            "at most one",
        ),
    ],
)
def test_config_validation(components, message):
    with pytest.raises(ConfigError, match=message):
        parse_config({"components": components}, "test")


def test_config_file_errors(tmp_path):
    bad = tmp_path / "c.json"
    bad.write_text("{nope")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(bad)
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.json")
    good = tmp_path / "g.json"
    good.write_text(json.dumps({"min_evidence_completeness": 2, "components": [
        {"name": "a", "source": "cell_attribute", "weight": 1}]}))
    with pytest.raises(ConfigError, match="min_evidence_completeness"):
        load_config(good)
