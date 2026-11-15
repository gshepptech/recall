from datetime import datetime, timezone

import pytest

from recall.scoring import clamp_confidence, compute_score, score


def _mem(**fields):
    return {"created_at": datetime.now(timezone.utc).isoformat(), "access_count": 0, **fields}


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("abc", None), (-1, 0.0), (0.4, 0.4), (7, 1.0)],
)
def test_clamp_confidence(value, expected):
    assert clamp_confidence(value) == expected


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [(None, 1.0), (1.0, 1.0), (0.5, 0.5), (0.0, 0.0)],
)
def test_score_scales_by_confidence(confidence, expected):
    assert score(1.0, _mem(confidence_score=confidence)) == pytest.approx(expected)


def test_compute_score_treats_zero_confidence_as_zero():
    assert compute_score(_mem(confidence_score=0.0)) == 0.0
