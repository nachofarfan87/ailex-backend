from __future__ import annotations

import unittest

from legal_engine.case_evaluation_engine import CaseEvaluationEngine


class TestCaseEvaluationEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = CaseEvaluationEngine()
        self.base_classification = {"confidence_score": 0.9, "action_slug": "alimentos_hijos"}
        self.base_case = {
            "facts": ["hijo menor", "incumplimiento", "convivencia materna"],
            "missing_information": [],
            "risks": [],
        }
        self.base_normative = {"applied_rules": [{}, {}, {}, {}], "unresolved_issues": []}
        self.base_questions = {"critical_questions": []}

    def test_high_risk_interaction_penalizes_strength(self) -> None:
        low = self.engine.evaluate(
            query="cuota alimentaria",
            classification=self.base_classification,
            case_structure=self.base_case,
            normative_reasoning=self.base_normative,
            question_engine_result=self.base_questions,
        )
        high = self.engine.evaluate(
            query="cuota alimentaria",
            classification=self.base_classification,
            case_structure={
                **self.base_case,
                "risks": [
                    "riesgo de incompetencia territorial",
                    "riesgo de falta de prueba de ingresos",
                    "riesgo de violencia economica sin documental",
                ],
                "missing_information": [
                    "domicilio actual del demandado",
                    "prueba de ingresos del obligado",
                ],
            },
            normative_reasoning={
                **self.base_normative,
                "unresolved_issues": [
                    "falta acreditar legitimacion",
                    "falta precisar competencia",
                    "falta sostener deuda con prueba",
                ],
            },
            question_engine_result={
                "critical_questions": [
                    "cual es el domicilio real",
                    "que ingresos comprobables existen",
                    "hay intimacion previa",
                ]
            },
        )
        self.assertGreater(high.risk_score, low.risk_score)
        self.assertLess(high.strength_score, low.strength_score)
        self.assertEqual(high.legal_risk_level, "alto")


if __name__ == "__main__":
    unittest.main()
