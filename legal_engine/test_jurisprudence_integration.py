from __future__ import annotations

import unittest

from legal_engine.jurisprudence_engine import (
    JurisprudenceAnalysisResult,
    JurisprudenceCase,
    JurisprudenceEngine,
    SOURCE_MODE_RETRIEVED,
    SOURCE_QUALITY_REAL,
    JURISPRUDENCE_STRENGTH_STRONG,
)
from legal_engine.normative_reasoner import NormativeReasoner, NormativeReasoningResult


class TestJurisprudenceIntegration(unittest.TestCase):
    def test_favorable_precedent_boosts_confidence(self) -> None:
        engine = JurisprudenceEngine()
        cases = [
            JurisprudenceCase(
                court="STJ",
                year=2024,
                case_name="Caso favorable",
                legal_issue="alimentos",
                decision_summary="Se hace lugar a la cuota provisoria",
                outcome="Hace lugar al reclamo",
                source_mode=SOURCE_MODE_RETRIEVED,
                retrieval_score=0.71,
                strategic_use="precedente favorable",
            )
        ]
        trend = engine._precedent_trend(cases)
        delta = engine._confidence_delta(
            precedent_trend=trend,
            source_quality=SOURCE_QUALITY_REAL,
            jurisprudence_strength=JURISPRUDENCE_STRENGTH_STRONG,
        )
        self.assertEqual(trend, "favorable")
        self.assertGreater(delta, 0.0)

    def test_adverse_precedent_penalizes_normative_reasoning(self) -> None:
        reasoner = NormativeReasoner()
        base = NormativeReasoningResult(
            summary="Base normativa cerrada.",
            legal_basis=["Art. 658 CCyC"],
            applied_rules=[],
            inferences=["La norma habilita el reclamo."],
            requirements=[],
            warnings=[],
            unresolved_issues=[],
            confidence_score=0.8,
        )
        enriched = reasoner.integrate_jurisprudence(
            normative_reasoning=base,
            jurisprudence_analysis={
                "precedent_trend": "adverse",
                "confidence_delta": -0.04,
                "reasoning_directive": "Los precedentes recuperados introducen cautela y obligan a acotar el alcance del razonamiento.",
            },
        )
        self.assertLess(enriched.confidence_score, base.confidence_score)
        self.assertIn("cautela", enriched.summary.lower())
        self.assertTrue(any("cautela" in item.lower() for item in enriched.warnings))


if __name__ == "__main__":
    unittest.main()
