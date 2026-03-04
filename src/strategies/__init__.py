"""Extraction strategies (api_contracts §2.3)."""

from src.strategies.base import ExtractorProtocol
from src.strategies.fast_text import FastTextExtractor
from src.strategies.layout import LayoutExtractor
from src.strategies.vision import VisionExtractor

__all__ = [
    "ExtractorProtocol",
    "FastTextExtractor",
    "LayoutExtractor",
    "VisionExtractor",
]