"""HLD 2: Green/Amber/Red rule using thresholds from src.config (internal to M1).

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Rule (problem statement 2b, section 4; thresholds in src.config):
- Green: adoption >= GREEN_MIN_ADOPTION and ROI > ROI_ZERO
- Red:   adoption <  RED_MAX_ADOPTION   or  ROI < ROI_ZERO
- Amber: everything else

Undefined inputs (None): a Red trigger that *can* be evaluated still makes the row Red;
otherwise the row is Amber, because Green needs both values to be known and passing.
"""
from __future__ import annotations

import logging

from src import config
from src.contracts import Status

logger = logging.getLogger(__name__)


def round_ratio(value: float | None) -> float | None:
    """Round a ratio to config.RATIO_DECIMALS so float noise never flips a threshold."""
    return None if value is None else round(value, config.RATIO_DECIMALS)


def portfolio_status(adoption: float | None, roi: float | None) -> Status:
    """Return 'Green', 'Amber' or 'Red' for one initiative's adoption and ROI (plain fractions)."""
    adoption, roi = round_ratio(adoption), round_ratio(roi)
    red_adoption = adoption is not None and adoption < config.RED_MAX_ADOPTION
    red_roi = roi is not None and roi < config.ROI_ZERO
    if red_adoption or red_roi:
        return "Red"
    if adoption is None or roi is None:
        logger.info("status Amber by default: adoption=%s roi=%s (undefined input)", adoption, roi)
        return "Amber"
    if adoption >= config.GREEN_MIN_ADOPTION and roi > config.ROI_ZERO:
        return "Green"
    return "Amber"
