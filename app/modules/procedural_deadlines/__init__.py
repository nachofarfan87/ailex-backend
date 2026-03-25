"""AILEX Procedural deadlines module."""

from app.modules.procedural_deadlines.calculator import calculate_deadline
from app.modules.procedural_deadlines.extractor import detect_deadlines
from app.modules.procedural_deadlines.models import DeadlineDetection

__all__ = [
    "DeadlineDetection",
    "detect_deadlines",
    "calculate_deadline",
]
