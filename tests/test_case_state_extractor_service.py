from __future__ import annotations

from app.services.case_state_extractor_service import case_state_extractor_service


def test_resuelve_case_type():
    extracted = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "classification": {"action_slug": "alimentos_hijos", "case_domain": "alimentos"},
            "query": "Quiero reclamar alimentos para mi hija",
        }
    )

    assert extracted["case_type"] == "alimentos_hijos"


def test_resuelve_primary_goal():
    extracted = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Quiero divorciarme cuanto antes",
            "classification": {"action_slug": "divorcio_unilateral", "case_domain": "divorcio"},
        }
    )

    assert extracted["primary_goal"] == "iniciar divorcio"


def test_genera_needs_desde_missing_facts():
    extracted = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Quiero reclamar alimentos",
            "missing_facts": ["ingresos_otro_progenitor"],
        }
    )

    assert len(extracted["needs"]) == 1
    assert extracted["needs"][0]["need_key"] == "hecho::ingresos_otro_progenitor"


def test_prioridad_critica_desde_critical_missing():
    extracted = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Quiero reclamar alimentos",
            "missing_facts": ["ingresos_otro_progenitor"],
            "critical_missing": ["ingresos_otro_progenitor"],
        }
    )

    assert extracted["needs"][0]["priority"] == "critical"


def test_stage_correcto_segun_facts_missing_y_output_mode():
    no_facts = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Necesito ayuda",
            "facts": {},
            "missing_facts": [],
        }
    )
    with_missing = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Quiero reclamar alimentos",
            "facts": {"hay_hijos": True},
            "critical_missing": ["ingresos_otro_progenitor"],
            "missing_facts": ["ingresos_otro_progenitor"],
        }
    )
    strategy_mode = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Quiero definir estrategia",
            "facts": {"hay_hijos": True},
            "output_mode": "estrategia",
        }
    )
    execution_mode = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Decime que hago mañana",
            "facts": {"hay_hijos": True},
            "output_mode": "ejecucion",
        }
    )

    assert no_facts["case_stage"] == "consulta_inicial"
    assert with_missing["case_stage"] == "recopilacion_hechos"
    assert strategy_mode["case_stage"] == "analisis_estrategico"
    assert execution_mode["case_stage"] == "ejecucion"


def test_need_key_con_namespace_se_conserva():
    extracted = case_state_extractor_service.extract_from_pipeline_payload(
        {
            "query": "Quiero reclamar alimentos",
            "missing_facts": [
                {
                    "need_key": "hecho::ingresos_otro_progenitor",
                    "reason": "Falta precisar ingresos",
                }
            ],
        }
    )

    assert extracted["needs"][0]["need_key"] == "hecho::ingresos_otro_progenitor"
