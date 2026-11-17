"""Smoke tests for shared files (contracts, config, seed data presence)."""
from datetime import date

from src import config
from src.contracts import METRIC_NAMES, Answer, InitiativeRecord


def test_config_paths_exist() -> None:
    assert config.SEED_DIR.is_dir()
    assert config.CHARTER_DIR.is_dir()
    assert config.TRUTH_DIR.is_dir()


def test_seven_metrics_declared() -> None:
    assert len(METRIC_NAMES) == 7


def test_models_validate() -> None:
    rec = InitiativeRecord(initiative_id="NIM-01", initiative_name="x", go_live_date=date(2021, 1, 1),
                           months_live=1, licensed_users=1, wau_week1=1, wau_week2=1, wau_week3=1,
                           total_cost_to_date_usd=1.0, realised_benefit_to_date_usd=1.0, planned_annual_benefit_usd=1.0)
    assert rec.initiative_id == "NIM-01"
    assert Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT).citations == []
