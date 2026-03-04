"""
ExtractionRouter (FR-2.5, FR-2.6, FR-2.8; api_contracts §2.2).
Selects strategy from DocumentProfile; delegates to extractor; escalates on low confidence; appends ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.config import RefineryConfig
from src.exceptions import ExtractionBudgetExceeded
from src.models.document_profile import DocumentProfile
from src.models.extracted_document import ExtractedDocument, LedgerEntry
from src.strategies.fast_text import FastTextExtractor
from src.strategies.layout import LayoutExtractor
from src.strategies.vision import VisionExtractor

# Strategy order for escalation: A -> B -> C
_STRATEGY_ORDER: list[tuple[str, type]] = [
    ("fast_text", FastTextExtractor),
    ("layout", LayoutExtractor),
    ("vision", VisionExtractor),
]


def _initial_strategy(profile: DocumentProfile) -> str:
    """Choose initial strategy from profile.estimated_extraction_cost (FR-2.5)."""
    cost = profile.estimated_extraction_cost
    if cost == "fast_text_sufficient":
        return "fast_text"
    if cost == "needs_layout_model":
        return "layout"
    return "vision"


def _next_strategy(current: str) -> str | None:
    """Return next strategy in escalation chain, or None if at end."""
    names = [s[0] for s in _STRATEGY_ORDER]
    try:
        i = names.index(current)
        if i + 1 < len(names):
            return names[i + 1]
    except ValueError:
        pass
    return None


def _append_ledger(config: RefineryConfig, entry: LedgerEntry) -> None:
    """Append one JSON line to extraction_ledger.jsonl (FR-2.8, DR-3)."""
    path = config.get_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = entry.model_dump_json() + "\n"
    path.open("a", encoding="utf-8").write(line)


class ExtractionRouter:
    """
    Routes extraction to Strategy A/B/C and escalates on low confidence.
    Writes every attempt to .refinery/extraction_ledger.jsonl.
    """

    def __init__(
        self,
        config: RefineryConfig | None = None,
        *,
        fast_text: FastTextExtractor | None = None,
        layout: LayoutExtractor | None = None,
        vision: VisionExtractor | None = None,
    ) -> None:
        from src.config import load_config

        self._config = config if config is not None else load_config()
        self._fast_text = fast_text or FastTextExtractor()
        self._layout = layout or LayoutExtractor()
        self._vision = vision or VisionExtractor()

    def _get_extractor(self, strategy_name: str):
        if strategy_name == "fast_text":
            return self._fast_text
        if strategy_name == "layout":
            return self._layout
        if strategy_name == "vision":
            return self._vision
        raise ValueError(f"Unknown strategy: {strategy_name}")

    def run(
        self,
        profile: DocumentProfile,
        document_path: Path | str,
        doc_id: str,
        config: RefineryConfig | None = None,
    ) -> ExtractedDocument:
        """
        Run extraction: select strategy from profile, run extractor, escalate if confidence low.
        Each attempt is appended to extraction_ledger.jsonl.

        Returns:
            ExtractedDocument from the chosen (possibly escalated) strategy.

        Raises:
            FileNotFoundError: If document_path does not exist.
            ExtractionBudgetExceeded: When Strategy C exceeds budget cap.
            ValidationError: On schema validation failure.
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        cfg = config or self._config
        threshold = cfg.extraction.confidence_escalation_threshold
        strategy_name = _initial_strategy(profile)
        escalated_from: str | None = None
        last_result = None

        while strategy_name is not None:
            extractor = self._get_extractor(strategy_name)
            try:
                result = extractor.extract(path, profile, cfg)
            except ExtractionBudgetExceeded:
                raise

            last_result = result
            processing_time = result.processing_time_seconds or 0.0
            cost_estimate = result.cost_estimate if result.cost_estimate is not None else 0.0

            entry = LedgerEntry(
                doc_id=doc_id,
                strategy_used=strategy_name,
                confidence_score=result.confidence_score,
                cost_estimate=cost_estimate,
                processing_time=processing_time,
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                escalated_from=escalated_from,
            )
            _append_ledger(cfg, entry)

            if result.confidence_score >= threshold:
                return result.document

            next_name = _next_strategy(strategy_name)
            if next_name is None:
                return result.document
            escalated_from = strategy_name
            strategy_name = next_name

        assert last_result is not None
        return last_result.document
