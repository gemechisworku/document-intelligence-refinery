"""Pytest fixtures for Document Intelligence Refinery."""

from __future__ import annotations

from pathlib import Path

import pytest


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def project_root() -> Path:
    """Project root directory."""
    return _project_root()


@pytest.fixture
def data_dir(project_root: Path) -> Path:
    """Corpus directory (data/data/)."""
    return project_root / "data" / "data"


@pytest.fixture
def sample_pdf_native_digital(data_dir: Path) -> Path | None:
    """Path to a native digital PDF (Class C or D)."""
    for name in (
        "fta_performance_survey_final_report_2022.pdf",
        "tax_expenditure_ethiopia_2021_22.pdf",
    ):
        p = data_dir / name
        if p.exists():
            return p
    return None


@pytest.fixture
def sample_pdf_scanned(data_dir: Path) -> Path | None:
    """Path to a scanned PDF (Class B)."""
    for name in (
        "2018_Audited_Financial_Statement_Report.pdf",
        "Audit Report - 2023.pdf",
    ):
        p = data_dir / name
        if p.exists():
            return p
    return None


@pytest.fixture
def temp_refinery_dir(tmp_path: Path):
    """Temporary .refinery directory for tests."""
    ref = tmp_path / ".refinery"
    ref.mkdir()
    (ref / "profiles").mkdir(parents=True)
    return ref
