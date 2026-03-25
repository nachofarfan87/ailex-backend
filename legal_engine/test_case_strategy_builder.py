from __future__ import annotations

import unittest
from types import SimpleNamespace

from legal_engine.case_strategy_builder import build_case_strategy


class TestCaseStrategyBuilder(unittest.TestCase):
    def _reasoning(self) -> SimpleNamespace:
        return SimpleNamespace(
            applied_analysis="ANALISIS JURIDICO -- JUJUY\nConsulta: test",
            short_answer="Respuesta base",
        )

    def _plan(self) -> SimpleNamespace:
        return SimpleNamespace(
            steps=[SimpleNamespace(action="Presentar demanda con documental inicial.")],
            risks=["Posible objecion por falta de acreditacion de ingresos."],
        )

    def test_narrative_varies_by_domain_and_risk(self) -> None:
        alimentos = build_case_strategy(
            query="cuota alimentaria provisoria",
            case_profile={
                "case_domain": "alimentos",
                "is_alimentos": True,
                "scenarios": ["cuota_provisoria", "incumplimiento"],
                "urgency_level": "high",
                "needs_proof_strengthening": False,
            },
            case_theory={"likely_points_of_conflict": ["discusion sobre capacidad contributiva"]},
            conflict={"most_vulnerable_point": "falta de recibos de sueldo"},
            case_evaluation={"legal_risk_level": "alto"},
            procedural_plan=self._plan(),
            jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
            reasoning_result=self._reasoning(),
        )
        patrimonial = build_case_strategy(
            query="division de inmueble",
            case_profile={
                "case_domain": "conflicto_patrimonial",
                "scenarios": ["cotitularidad", "conflicto"],
                "needs_proof_strengthening": True,
            },
            case_theory={"evidentiary_needs": ["titulo actualizado", "informe registral"]},
            conflict={"most_vulnerable_point": "falta de titulo inscripto"},
            case_evaluation={"legal_risk_level": "medio"},
            procedural_plan=self._plan(),
            jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
            reasoning_result=self._reasoning(),
        )
        self.assertNotEqual(alimentos["strategic_narrative"], patrimonial["strategic_narrative"])
        self.assertIn("tutela inmediata", alimentos["strategic_narrative"])
        self.assertIn("titularidad", patrimonial["strategic_narrative"])


if __name__ == "__main__":
    unittest.main()
