from __future__ import annotations

from app.services.core_legal_response_service import build_core_legal_response


def test_build_core_legal_response_prioritizes_direct_answer_steps_and_local_notes():
    payload = {
        "query": "Quiero divorciarme en Jujuy",
        "jurisdiction": "jujuy",
        "case_domain": "divorcio",
        "reasoning": {
            "short_answer": "Si no hay acuerdo, en principio el divorcio puede promoverse igual de forma unilateral.",
        },
        "quick_start": "Primer paso recomendado: Preparar presentacion inicial de divorcio.",
        "case_strategy": {
            "recommended_actions": [
                "Redactar propuesta reguladora unilateral con todos los efectos del divorcio.",
                "Incluir en la propuesta cuidado personal, regimen comunicacional y alimentos para los hijos.",
            ],
            "procedural_focus": [
                "Verificar competencia y ultimo domicilio conyugal.",
            ],
            "ordinary_missing_information": [
                "Reunir DNI y acta o libreta de matrimonio.",
            ],
            "conflict_summary": [
                "Existe conflicto sobre los efectos del divorcio.",
            ],
        },
        "procedural_strategy": {
            "missing_information": [
                "Reunir documentacion del matrimonio y domicilios relevantes.",
            ],
        },
        "conversational": {
            "question": "¿Hay hijos menores o con capacidad restringida?",
        },
    }

    result = build_core_legal_response(payload)

    assert result["direct_answer"]
    assert result["action_steps"]
    assert any("presentacion inicial" in item.lower() or "propuesta reguladora" in item.lower() for item in result["action_steps"])
    assert result["required_documents"]
    assert any("matrimonio" in item.lower() or "dni" in item.lower() for item in result["required_documents"])
    assert result["local_practice_notes"]
    assert any("jujuy" in item.lower() or "propuesta reguladora" in item.lower() for item in result["local_practice_notes"])
    assert result["professional_frame"]["checklist"]
    assert result["optional_clarification"] == "¿Hay hijos menores o con capacidad restringida?"


def test_build_core_legal_response_generates_succession_defaults_when_documents_missing():
    payload = {
        "jurisdiction": "jujuy",
        "case_domain": "sucesion",
        "reasoning": {
            "short_answer": "La sucesion puede iniciarse con la documentacion basica del fallecimiento y del parentesco.",
        },
    }

    result = build_core_legal_response(payload)

    assert any("defuncion" in item.lower() for item in result["required_documents"])
    assert any("parentesco" in item.lower() for item in result["required_documents"])
