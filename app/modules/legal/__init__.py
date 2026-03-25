"""Legal workflows and extraction helpers."""

from app.modules.legal.analyze_notification import analyze_notification
from legal_sources.load_norms import load_normative_corpus

__all__ = [
    "analyze_notification",
    "load_normative_corpus",
]
