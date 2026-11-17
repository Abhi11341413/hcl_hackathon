"""Unit tests for src.scorecard.status (owner: M1)."""
import pytest

from src.scorecard.status import portfolio_status, round_ratio


@pytest.mark.parametrize("adoption, roi, expected", [
    (0.60, 0.12, "Green"),            # adoption exactly at the Green threshold
    (0.80, 0.0, "Amber"),             # ROI exactly 0 is not > 0
    (0.80, -1e-12, "Amber"),          # float noise rounds to 0 -> still Amber
    (0.80, -0.22, "Red"),             # ROI < 0
    (0.2875, 0.05, "Red"),            # adoption < 0.30
    (0.30, 0.05, "Amber"),            # adoption exactly 0.30 is not Red
    (0.5999999999999, 0.5, "Green"),  # rounds to 0.60
    (0.45, 0.18, "Amber"),
])
def test_portfolio_status(adoption, roi, expected) -> None:
    assert portfolio_status(adoption, roi) == expected


@pytest.mark.parametrize("adoption, roi, expected", [
    (None, 0.5, "Amber"),    # Green needs both inputs
    (0.9, None, "Amber"),
    (None, -0.1, "Red"),     # a Red trigger that can be checked still applies
    (0.1, None, "Red"),
    (None, None, "Amber"),
])
def test_portfolio_status_with_undefined_inputs(adoption, roi, expected) -> None:
    assert portfolio_status(adoption, roi) == expected


def test_round_ratio() -> None:
    assert round_ratio(None) is None
    assert round_ratio(1 / 3) == 0.3333333333
