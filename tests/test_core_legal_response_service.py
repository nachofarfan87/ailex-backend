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


def test_divorce_without_details_still_returns_minimum_useful_documents_and_steps():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero divorciarme.",
    })

    assert any("dni" in item.lower() for item in result["required_documents"])
    assert any("matrimonio" in item.lower() or "libreta" in item.lower() for item in result["required_documents"])
    assert any("presentacion inicial" in item.lower() or "propuesta reguladora" in item.lower() for item in result["action_steps"])
    assert result["optional_clarification"] is not None


def test_cuidado_personal_returns_useful_base_even_with_limited_information():
    result = build_core_legal_response({
        "case_domain": "cuidado_personal",
        "jurisdiction": "jujuy",
        "query": "Quiero resolver el cuidado de mi hijo.",
    })

    assert "cuidado" in result["direct_answer"].lower()
    assert any("centro de vida" in item.lower() or "partida" in item.lower() for item in result["required_documents"])
    assert any("convive" in item.lower() or "presentacion inicial" in item.lower() for item in result["action_steps"])


def test_divorce_in_jujuy_includes_local_family_forum_and_filing_shape():
    result = build_core_legal_response({
        "case_domain": "divorcio",
        "jurisdiction": "jujuy",
        "query": "Quiero divorciarme y solo yo quiero hacerlo.",
        "conversational": {
            "known_facts": {
                "hay_acuerdo": False,
            },
        },
    })

    joined_notes = " ".join(result["local_practice_notes"]).lower()
    joined_steps = " ".join(result["action_steps"]).lower()
    joined_answer = result["direct_answer"].lower()

    assert "fuero de familia" in joined_notes
    assert "propuesta reguladora" in joined_steps or "peticion de divorcio" in joined_steps
    assert "fuero de familia" in joined_answer or "presentacion" in joined_answer


def test_alimentos_in_jujuy_mentions_family_forum_and_provisional_support():
    result = build_core_legal_response({
        "case_domain": "alimentos",
        "jurisdiction": "jujuy",
        "query": "Quiero reclamar alimentos para mi hijo porque no me pasa plata.",
    })

    joined_notes = " ".join(result["local_practice_notes"]).lower()
    joined_steps = " ".join(result["action_steps"]).lower()

    assert "fuero de familia" in joined_notes
    assert "cuota provisoria" in joined_notes or "cuota provisoria" in joined_steps
    assert any("gastos" in item.lower() for item in result["required_documents"])


def test_sucesion_includes_civil_orientation_and_last_domicile():
    result = build_core_legal_response({
        "case_domain": "sucesion",
        "jurisdiction": "jujuy",
        "query": "Quiero iniciar la sucesion de mi papa.",
    })

    joined_notes = " ".join(result["local_practice_notes"]).lower()
    joined_answer = result["direct_answer"].lower()
    joined_steps = " ".join(result["action_steps"]).lower()

    assert "sede civil" in joined_notes or "sede civil" in joined_answer
    assert "ultimo domicilio" in joined_notes or "ultimo domicilio" in joined_steps


def test_civil_cobro_opens_useful_collection_guidance():
    result = build_core_legal_response({
        "case_domain": "civil",
        "jurisdiction": "jujuy",
        "query": "Me deben plata por un contrato y no me pagan.",
    })

    assert result["focus_trace"]["practical_domain"] == "civil_cobro"
    assert "deuda" in result["direct_answer"].lower() or "incumplimiento" in result["direct_answer"].lower()
    assert any("contrato" in item.lower() or "deuda" in item.lower() for item in result["required_documents"])
    assert result["professional_frame"]["practical_domain_label"] == "Cobro e incumplimiento civil"


def test_civil_danos_opens_damage_guidance():
    result = build_core_legal_response({
        "case_domain": "civil",
        "jurisdiction": "jujuy",
        "query": "Tuve un choque y quiero reclamar los daños del auto y las lesiones.",
    })

    assert result["focus_trace"]["practical_domain"] == "civil_danos"
    assert "dano" in result["direct_answer"].lower() or "accidente" in result["direct_answer"].lower()
    assert any("denuncia" in item.lower() or "certificados medicos" in item.lower() or "fotos" in item.lower() for item in result["required_documents"])
    joined_notes = " ".join(result["local_practice_notes"]).lower()
    assert "jujuy" in joined_notes or "danos y perjuicios" in joined_notes or "prueba del hecho" in joined_notes


def test_civil_inmueble_opens_property_conflict_guidance():
    result = build_core_legal_response({
        "case_domain": "civil",
        "jurisdiction": "jujuy",
        "query": "Tengo un problema con un alquiler y quiero reclamar por el inmueble.",
    })

    assert result["focus_trace"]["practical_domain"] == "civil_inmueble"
    assert "inmueble" in result["direct_answer"].lower() or "alquiler" in result["direct_answer"].lower()
    assert any("contrato" in item.lower() or "escritura" in item.lower() for item in result["required_documents"])
    assert result["professional_frame"]["practical_domain_label"] == "Conflicto civil sobre inmueble"


def test_sucesion_branch_still_activates_even_if_case_domain_is_civil():
    result = build_core_legal_response({
        "case_domain": "civil",
        "action_slug": "sucesion_ab_intestato",
        "jurisdiction": "jujuy",
        "query": "Quiero iniciar la sucesion de mi madre.",
    })

    assert result["focus_trace"]["practical_domain"] == "sucesion"
    assert "sucesion" in result["direct_answer"].lower()
    assert any("defuncion" in item.lower() for item in result["required_documents"])
