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
            "question": "Hay hijos menores o con capacidad restringida?",
        },
    }

    result = build_core_legal_response(payload)

    assert result["direct_answer"]
    assert len(result["direct_answer"].splitlines()) >= 3
    assert result["action_steps"]
    assert any(
        "presentacion inicial" in item.lower() or "propuesta reguladora" in item.lower()
        for item in result["action_steps"]
    )
    assert result["required_documents"]
    assert any("matrimonio" in item.lower() or "dni" in item.lower() for item in result["required_documents"])
    assert result["local_practice_notes"]
    assert any("jujuy" in item.lower() or "propuesta reguladora" in item.lower() for item in result["local_practice_notes"])
    assert result["professional_frame"]["checklist"]
    assert result["optional_clarification"]
    assert "hijos" in result["optional_clarification"].lower()
    assert (
        "cuidado" in result["optional_clarification"].lower()
        or "alimentos" in result["optional_clarification"].lower()
    )


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


def test_divorce_with_children_prioritizes_children():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero divorciarme y tengo hijos menores.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
        "conversational": {
            "known_facts": {
                "hay_hijos": True,
            },
        },
    })

    assert "cuidado personal" in result["direct_answer"].lower()
    assert "alimentos" in result["direct_answer"].lower()
    assert any("cuidado personal" in item.lower() for item in result["action_steps"])
    assert result["focus_trace"]["primary_focus"] == "children"


def test_divorce_with_property_prioritizes_property():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero divorciarme y discutir la division de bienes y la escritura de un inmueble.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
    })

    assert result["focus_trace"]["primary_focus"] == "property"
    assert "bienes" in result["direct_answer"].lower() or "patrimonial" in result["direct_answer"].lower()
    assert any("escritura" in item.lower() or "bienes" in item.lower() for item in result["action_steps"])


def test_divorce_with_children_and_urgency_prioritizes_protection():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero divorciarme, tengo una bebe de 3 meses y el otro progenitor no pasa alimentos. Necesito algo urgente.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
        "conversational": {
            "known_facts": {
                "hay_hijos": True,
            },
        },
    })

    assert result["focus_trace"]["primary_focus"] == "protection_urgency"
    assert "urgencia" in result["direct_answer"].lower() or "proteccion" in result["direct_answer"].lower()
    assert "children" in result["focus_trace"]["secondary_focuses"]


def test_mixed_case_keeps_primary_and_secondary_focuses():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero divorciarme, tenemos hijos y tambien esta en juego la vivienda familiar.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
        "conversational": {
            "known_facts": {
                "hay_hijos": True,
            },
        },
    })

    assert result["focus_trace"]["primary_focus"] == "children"
    assert "housing" in result["focus_trace"]["secondary_focuses"]
    assert "vivienda" in result["direct_answer"].lower()


def test_general_case_keeps_stable_fallback():
    result = build_core_legal_response({
        "case_domain": "civil",
        "jurisdiction": "jujuy",
        "query": "No se como iniciar mi reclamo.",
        "reasoning": {
            "short_answer": "Conviene ordenar el problema y definir el primer paso.",
        },
    })

    assert result["focus_trace"]["primary_focus"] in ("procedure", "general")
    assert result["direct_answer"]
    assert result["action_steps"]


def test_colloquial_contact_block_prioritizes_protection():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero separarme y no me deja ver a mi hija.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
    })

    assert result["focus_trace"]["primary_focus"] == "protection_urgency"
    assert "proteccion" in result["direct_answer"].lower() or "urgencia" in result["direct_answer"].lower()
    assert result["focus_trace"]["focus_reason"]


def test_colloquial_housing_with_children_prioritizes_children_and_keeps_housing_secondary():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Me quiero divorciar y no se donde voy a vivir con mis hijos.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
    })

    assert result["focus_trace"]["primary_focus"] == "children"
    assert "housing" in result["focus_trace"]["secondary_focuses"]
    assert "vivienda" in result["direct_answer"].lower()


def test_colloquial_baby_and_no_money_prioritizes_protection():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero divorciarme, hay una bebe de meses y no me pasa plata.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
    })

    assert result["focus_trace"]["primary_focus"] == "protection_urgency"
    assert "children" in result["focus_trace"]["secondary_focuses"]
    assert any("urgente" in item.lower() or "proteccion" in item.lower() for item in result["action_steps"])


def test_colloquial_divide_house_keeps_non_general_focus():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Nos queremos divorciar y dividir la casa.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
    })

    assert result["focus_trace"]["primary_focus"] in ("housing", "property")
    assert result["focus_trace"]["focus_reason"]


def test_simple_divorce_keeps_general_or_procedure_without_breaking_output():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero iniciar divorcio.",
        "reasoning": {
            "short_answer": "El divorcio puede iniciarse aunque no haya acuerdo.",
        },
    })

    assert result["focus_trace"]["primary_focus"] in ("general", "procedure")
    assert result["direct_answer"]
    assert result["action_steps"]
