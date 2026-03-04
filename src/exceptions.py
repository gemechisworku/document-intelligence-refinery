"""Exceptions for pipeline stages (api_contracts §7)."""


class ExtractionBudgetExceeded(Exception):
    """Strategy C per-document token/cost exceeds config cap (FR-2.9, BR-3)."""

    pass
