"""Unit tests for Triage Agent classification (DC-3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.triage import (
    KeywordDomainClassifier,
    TriageAgent,
    _classify_origin_type,
    _classify_layout_complexity,
)
from src.config import RefineryConfig, TriageConfig
from src.models.document_profile import DocumentProfile


@pytest.fixture
def triage_agent(temp_refinery_dir: Path) -> TriageAgent:
    """Triage agent with temp refinery dir."""
    config = RefineryConfig(refinery_dir=temp_refinery_dir)
    return TriageAgent(config=config)


@pytest.fixture
def triage_config() -> TriageConfig:
    """Default triage config for unit tests."""
    return TriageConfig()


def test_triage_produces_valid_document_profile(
    triage_agent: TriageAgent,
    sample_pdf_native_digital: Path | None,
    temp_refinery_dir: Path,
) -> None:
    """Given a native digital PDF, run() returns a DocumentProfile that validates."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found (data/data/)")
    doc_id = "test_fta"
    profile = triage_agent.run(sample_pdf_native_digital, doc_id)
    assert isinstance(profile, DocumentProfile)
    assert profile.doc_id == doc_id
    assert profile.origin_type in ("native_digital", "mixed")
    assert profile.layout_complexity in (
        "single_column",
        "multi_column",
        "table_heavy",
        "figure_heavy",
        "mixed",
    )
    assert profile.domain_hint in ("financial", "legal", "technical", "medical", "general")
    assert profile.estimated_extraction_cost in (
        "fast_text_sufficient",
        "needs_layout_model",
        "needs_vision_model",
    )
    assert 0 <= profile.language_confidence <= 1
    # Profile persisted
    profile_path = temp_refinery_dir / "profiles" / f"{doc_id}.json"
    assert profile_path.exists()
    reloaded = DocumentProfile.model_validate_json(profile_path.read_text())
    assert reloaded.doc_id == profile.doc_id
    assert reloaded.origin_type == profile.origin_type


def test_triage_classifies_scanned_as_scanned_image(
    triage_agent: TriageAgent,
    sample_pdf_scanned: Path | None,
) -> None:
    """Given a scanned PDF, profile has origin_type scanned_image (or mixed if sparse text)."""
    if sample_pdf_scanned is None:
        pytest.skip("No scanned corpus PDF found")
    profile = triage_agent.run(sample_pdf_scanned, "test_scanned")
    # 2018_Audited has no text stream; Audit Report has minimal text on p1
    assert profile.origin_type in ("scanned_image", "mixed")
    assert profile.estimated_extraction_cost in ("needs_layout_model", "needs_vision_model")


def test_triage_raises_file_not_found(triage_agent: TriageAgent, tmp_path: Path) -> None:
    """run() raises FileNotFoundError when document path does not exist."""
    with pytest.raises(FileNotFoundError, match="Document not found"):
        triage_agent.run(tmp_path / "nonexistent.pdf", "doc1")


def test_triage_deterministic(
    triage_agent: TriageAgent,
    sample_pdf_native_digital: Path | None,
    temp_refinery_dir: Path,
) -> None:
    """Same document + config yields same profile (NFR-4)."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found")
    doc_id = "deterministic_test"
    p1 = triage_agent.run(sample_pdf_native_digital, doc_id)
    # Run again (overwrite profile)
    p2 = triage_agent.run(sample_pdf_native_digital, doc_id)
    assert p1.origin_type == p2.origin_type
    assert p1.layout_complexity == p2.layout_complexity
    assert p1.estimated_extraction_cost == p2.estimated_extraction_cost


# -----------------------------------------------------------------------------
# Zero-text, mixed-mode, form-fillable (explicit handling)
# -----------------------------------------------------------------------------


def test_triage_zero_text_classified_as_scanned_image(
    triage_agent: TriageAgent,
    sample_pdf_native_digital: Path | None,
) -> None:
    """When PDF has no extractable text (zero-text), origin_type is scanned_image."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found")
    zero_text_analysis = {
        "has_text_stream": False,
        "chars_per_page_avg": 0.0,
        "image_area_ratio_avg": 0.2,
        "pages_analyzed": 3,
        "total_chars": 0,
    }
    with (
        patch("src.agents.triage._analyze_pdf", return_value=zero_text_analysis),
        patch("src.agents.triage._pdf_has_acroform", return_value=False),
    ):
        profile = triage_agent.run(sample_pdf_native_digital, "zero_text_doc")
    assert profile.origin_type == "scanned_image"
    assert profile.estimated_extraction_cost == "needs_vision_model"


def test_classify_origin_mixed_mode(triage_config: TriageConfig) -> None:
    """Signals in between scanned and native bands yield mixed."""
    origin = _classify_origin_type(
        has_text_stream=True,
        chars_per_page_avg=300.0,
        image_ratio_avg=0.25,
        pages_analyzed=5,
        total_chars=1500,
        form_fillable=False,
        cfg=triage_config,
    )
    assert origin == "mixed"


def test_triage_form_fillable_detected(
    triage_agent: TriageAgent,
    sample_pdf_native_digital: Path | None,
) -> None:
    """When PDF has AcroForm and text, origin_type is form_fillable."""
    if sample_pdf_native_digital is None:
        pytest.skip("No corpus PDF found")
    with (
        patch("src.agents.triage._analyze_pdf") as mock_analyze,
        patch("src.agents.triage._pdf_has_acroform", return_value=True),
    ):
        mock_analyze.return_value = {
            "has_text_stream": True,
            "chars_per_page_avg": 400.0,
            "image_area_ratio_avg": 0.1,
            "pages_analyzed": 2,
            "total_chars": 800,
        }
        profile = triage_agent.run(sample_pdf_native_digital, "form_doc")
    assert profile.origin_type == "form_fillable"
    assert profile.estimated_extraction_cost == "needs_layout_model"


# -----------------------------------------------------------------------------
# Domain from config (add keywords by editing config only)
# -----------------------------------------------------------------------------


def test_domain_classifier_uses_config_keywords() -> None:
    """KeywordDomainClassifier returns domain from config-driven keyword lists."""
    config = TriageConfig(
        domain_keywords={
            "financial": ["revenue", "annual report"],
            "legal": ["compliance"],
            "technical": ["survey", "custom_technical_term"],
            "medical": ["clinical"],
            "general": [],
        }
    )
    classifier = KeywordDomainClassifier()
    assert classifier.classify(Path("revenue_2024.pdf"), config) == "financial"
    assert classifier.classify(Path("compliance_check.pdf"), config) == "legal"
    assert classifier.classify(Path("report_with_custom_technical_term.pdf"), config) == "technical"
    assert classifier.classify(Path("clinical_study.pdf"), config) == "medical"
    assert classifier.classify(Path("misc_notes.pdf"), config) == "general"


def test_domain_classifier_first_match_wins() -> None:
    """First matching domain in config order wins (e.g. financial before legal)."""
    config = TriageConfig(
        domain_keywords={
            "financial": ["audit"],
            "legal": ["audit", "legal"],
            "technical": [],
            "medical": [],
            "general": [],
        }
    )
    classifier = KeywordDomainClassifier()
    # "audit" matches financial first (we iterate financial, legal, ...)
    assert classifier.classify(Path("audit_report.pdf"), config) == "financial"


def test_layout_complexity_uses_config_thresholds(triage_config: TriageConfig) -> None:
    """Layout classification uses thresholds from config, not hardcoded values."""
    # High image ratio -> figure_heavy (threshold from config)
    layout = _classify_layout_complexity(
        chars_per_page_avg=100.0,
        image_ratio_avg=0.5,
        cfg=triage_config,
    )
    assert layout == "figure_heavy"
    # Low image, high chars -> table_heavy
    layout2 = _classify_layout_complexity(
        chars_per_page_avg=2000.0,
        image_ratio_avg=0.05,
        cfg=triage_config,
    )
    assert layout2 == "table_heavy"
