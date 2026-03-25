from legal_engine.argument_generator import ArgumentGenerator
from legal_engine.ailex_pipeline import AilexPipeline


def _reasoning_payload():
    return {
        "short_answer": "Procede trabajar la pretension con apoyo normativo suficiente.",
        "applied_analysis": "La viabilidad de la pretension depende de conectar el conflicto con los requisitos legales y con la prueba actualmente reunida.",
        "jurisdiction": "jujuy",
        "domain": "family",
        "confidence": 0.82,
        "normative_foundations": [
            {
                "source": "codigo_civil_comercial",
                "article": "438",
                "summary": "La peticion de divorcio requiere una propuesta reguladora.",
                "description": "Sirve para sostener el encuadre normativo del planteo.",
            },
            {
                "source": "codigo_civil_comercial",
                "article": "439",
                "summary": "El juez controla los efectos del divorcio cuando corresponde.",
                "description": "Permite ordenar el debate sobre efectos familiares y patrimoniales.",
            },
        ],
    }


def _reasoning_payload_many_norms():
    payload = _reasoning_payload()
    payload["normative_foundations"] = [
        {
            "source": "codigo_civil_comercial",
            "article": str(430 + idx),
            "summary": f"Norma {idx} de prueba para medir densidad normativa.",
            "description": f"Descripcion {idx}.",
        }
        for idx in range(1, 7)
    ]
    return payload


def _strategy_payload():
    return {
        "next_steps": [
            "Consolidar la prueba documental basica.",
            "Ordenar el relato de hechos y el conflicto principal.",
        ],
        "risks": [
            "La insuficiencia de prueba puede debilitar la pretension.",
        ],
        "missing_information": [
            "Detalle patrimonial relevante.",
        ],
        "strategic_notes": "Conviene llegar al escrito con una hipotesis de caso clara.",
    }


def _common_kwargs():
    return {
        "classification": {"action_label": "Divorcio por presentacion conjunta", "forum": "familia"},
        "case_structure": {"main_claim": "Peticion conjunta de divorcio con propuesta reguladora.", "forum": "familia"},
        "case_theory": {
            "primary_theory": "Existe voluntad concurrente de disolver el vinculo y ordenar sus efectos.",
            "objective": "Obtener sentencia de divorcio con control judicial de la propuesta.",
            "key_facts_supporting": ["Los conyuges expresan voluntad concurrente de divorciarse."],
            "likely_points_of_conflict": ["Alcance de la propuesta reguladora."],
            "evidentiary_needs": ["Partida de matrimonio.", "Propuesta reguladora."],
            "recommended_line_of_action": ["Definir una propuesta reguladora completa antes de presentar."],
        },
        "case_evaluation": {
            "case_strength": "medium",
            "legal_risk_level": "medium",
            "uncertainty_level": "low",
            "strategic_observations": ["Conviene reforzar prueba documental antes de litigar."],
            "possible_scenarios": ["Observacion judicial de la propuesta reguladora."],
        },
        "conflict_evidence": {
            "core_dispute": "Definir de manera suficiente los efectos personales y patrimoniales del divorcio.",
            "strongest_point": "La voluntad concurrente reduce el conflicto sobre la disolucion del vinculo.",
            "most_vulnerable_point": "La propuesta reguladora incompleta puede generar observaciones judiciales.",
            "recommended_evidence_actions": ["Acompanhar la propuesta reguladora firmada."],
        },
        "evidence_reasoning_links": {
            "summary": "La base probatoria debe cubrir los requisitos principales del planteo.",
            "requirement_links": [
                {
                    "source": "codigo_civil_comercial",
                    "article": "438",
                    "requirement": "Presentar propuesta reguladora.",
                    "support_level": "medio",
                    "evidence_missing": ["Propuesta reguladora completa."],
                    "strategic_note": "Sin propuesta suficiente el planteo pierde densidad.",
                }
            ],
        },
        "normative_reasoning": {
            "inferences": ["La falta de propuesta reguladora afecta la solidez de la presentacion."],
            "requirements": ["Presentar una propuesta reguladora suficiente."],
            "applied_rules": [
                {"source": "CCyC", "article": "438", "effect": "Exige propuesta reguladora en el planteo de divorcio."}
            ],
        },
    }


def test_formal_real_strong_raises_argumental_density():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        jurisprudence_analysis={
            "source_quality": "real",
            "jurisprudence_strength": "strong",
            "usable_real_precedents": 2,
            "jurisprudence_highlights": [
                {
                    "case_name": "LLAMPA",
                    "court": "Tribunal de Familia de Jujuy",
                    "year": 2024,
                    "criterion": "La propuesta reguladora suficiente ordena los efectos del divorcio y evita observaciones innecesarias.",
                    "strategic_use": "Sirve para sostener un planteo inicial completo y prevenir observaciones del juzgado.",
                    "source_mode": "retrieved_real_precedent",
                }
            ],
        },
        **_common_kwargs(),
    )

    assert "PUNTO DE CONFLICTO Y HECHOS DECISIVOS" in result.full_text
    assert "REQUISITOS CRITICOS Y SOPORTE" in result.full_text
    assert "precedentes reales recuperados del corpus" in result.full_text.lower()
    assert "LLAMPA" in result.full_text


def test_fallback_internal_is_not_presented_as_real_precedent():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        jurisprudence_analysis={
            "source_quality": "fallback",
            "jurisprudence_strength": "weak",
            "used_internal_fallback": True,
            "jurisprudence_highlights": [
                {
                    "case_name": "Perfil interno",
                    "court": "No deberia mostrarse",
                    "criterion": "Orienta de forma preliminar el planteo.",
                    "strategic_use": "Solo orienta internamente el orden del analisis.",
                    "source_mode": "internal_fallback_profile",
                }
            ],
        },
        **_common_kwargs(),
    )

    lowered = result.full_text.lower()
    assert "perfil interno orientativo, no precedente real recuperado del corpus" in lowered
    assert "tribunal: no deberia mostrarse" not in lowered


def test_base_argumental_prioritizes_conflict_proof_and_action_without_real_support():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        jurisprudence_analysis={
            "source_quality": "none",
            "jurisprudence_strength": "none",
            "should_limit_claims": True,
            "should_avoid_jurisprudential_assertions": True,
        },
        **_common_kwargs(),
    )

    lowered = result.full_text.lower()
    assert "hecho decisivo y punto de conflicto" in lowered
    assert "linea de accion inmediata" in lowered
    assert "sin respaldo jurisprudencial consolidado" in lowered


def test_pipeline_formal_document_includes_strategic_sections():
    payload = AilexPipeline().run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
        document_mode="formal",
    ).to_dict()

    document = payload["generated_document"] or ""
    lowered = document.lower()
    assert "punto de conflicto y hechos decisivos" in lowered
    assert "riesgo procesal y cobertura probatoria" in lowered


def test_alimentos_formal_pushes_cuota_provisoria_and_immediate_proof():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="el padre no paga alimentos y necesito cuota provisoria",
        mode="formal",
        reasoning={
            **_reasoning_payload(),
            "domain": "family",
        },
        strategy={
            **_strategy_payload(),
            "next_steps": ["Promover demanda con pedido de cuota provisoria."],
        },
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos", "forum": "familia"},
        case_theory={
            "primary_theory": "Existe incumplimiento alimentario actual del progenitor no conviviente.",
            "objective": "Obtener fijacion urgente de cuota alimentaria provisoria.",
            "key_facts_supporting": ["El progenitor no conviviente no esta cumpliendo regularmente."],
            "likely_points_of_conflict": ["Capacidad economica del alimentante."],
            "evidentiary_needs": ["Comprobantes de gastos del hijo.", "Datos de ingresos del alimentante."],
            "recommended_line_of_action": ["Acompanhar comprobantes de gastos y pedir cuota provisoria."],
        },
        conflict_evidence={
            "core_dispute": "Incumplimiento de la obligacion alimentaria respecto del hijo.",
            "strongest_point": "Las necesidades actuales del hijo ya aparecen identificadas.",
            "most_vulnerable_point": "Aun falta reconstruccion patrimonial completa del alimentante.",
            "recommended_evidence_actions": ["Acompanhar gastos de escolaridad, salud y alimentacion."],
        },
        normative_reasoning={
            "requirements": ["Acreditar necesidades del hijo."],
            "inferences": ["La urgencia alimentaria justifica tutela inmediata."],
            "applied_rules": [{"source": "CCyC", "article": "658", "effect": "Existe obligacion alimentaria."}],
        },
    )

    lowered = result.full_text.lower()
    assert "cuota provisoria" in lowered
    assert "prueba inmediata" in lowered or "comprobantes concretos" in lowered


def test_alimentos_vulnerability_reflects_protection_without_genericity():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="alimentos para mi hijo con bajos recursos y auh",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos", "forum": "familia"},
        case_theory={
            "primary_theory": "La progenitora conviviente carece de recursos suficientes y requiere tutela reforzada.",
            "objective": "Obtener alimentos con cobertura minima suficiente.",
            "evidentiary_needs": ["Constancias de AUH.", "Datos de CBU para pagos."],
            "recommended_line_of_action": ["Solicitar justicia gratuita y ordenar constancias de ANSES."],
        },
        conflict_evidence={
            "core_dispute": "La cobertura alimentaria actual es insuficiente para necesidades basicas.",
            "most_vulnerable_point": "Bajos recursos y dependencia de prestaciones sociales.",
        },
        normative_reasoning={"requirements": ["Acreditar necesidades basicas del hijo."]},
    )

    lowered = result.full_text.lower()
    assert "justicia gratuita" in lowered
    assert "anses" in lowered or "auh" in lowered or "smvm" in lowered


def test_alimentos_ascendants_explains_subsidiarity_clearly():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="alimentos contra abuelo por imposibilidad del obligado principal",
        mode="memorial",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos", "forum": "familia"},
        case_theory={
            "primary_theory": "Corresponde desplazar el reclamo hacia el ascendiente por insuficiencia del obligado principal.",
            "objective": "Obtener alimentos contra ascendiente en caracter subsidiario.",
            "recommended_line_of_action": ["Explicar la subsidiariedad y la imposibilidad del obligado principal."],
        },
        conflict_evidence={
            "core_dispute": "Subsidiariedad del reclamo alimentario contra ascendiente.",
            "most_vulnerable_point": "Necesidad de probar imposibilidad del obligado principal.",
        },
        normative_reasoning={"requirements": ["Acreditar insuficiencia del obligado principal."]},
    )

    lowered = result.full_text.lower()
    assert "subsidiariedad" in lowered
    assert "obligado principal" in lowered


def test_alimentos_hijo_mayor_estudiante_is_not_treated_as_standard_case():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="alimentos para hijo mayor estudiante universitario",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos", "forum": "familia"},
        case_theory={
            "primary_theory": "El hijo mayor continua estudiando y requiere asistencia alimentaria.",
            "objective": "Obtener alimentos para hijo mayor estudiante.",
            "evidentiary_needs": ["Certificado de alumno regular.", "Constancias de continuidad academica."],
        },
        conflict_evidence={
            "core_dispute": "Continuidad de asistencia alimentaria para hijo mayor estudiante.",
            "most_vulnerable_point": "Necesidad de acreditar regularidad academica.",
        },
        normative_reasoning={
            "requirements": ["Acreditar regularidad academica."],
            "applied_rules": [{"source": "CCyC", "article": "663", "effect": "Permite alimentos al hijo mayor que estudia."}],
        },
    )

    lowered = result.full_text.lower()
    assert "663 ccyc" in lowered or "art. 663" in lowered
    assert "regularidad academica" in lowered


def test_blueprint_drives_real_section_order():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_directives": {
                "tone": "technical_robust",
            },
            "style_blueprint": {
                "section_order": ["encabezado", "riesgo_procesal", "marco_normativo", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["riesgo_procesal", "marco_normativo"],
                "section_templates": {
                    "riesgo_procesal": {"required": True, "max_paragraphs": 2},
                    "marco_normativo": {"required": True, "density": "high"},
                },
                "content_rules": {
                    "include_jurisprudence": "never",
                    "normative_density": "high",
                    "argument_style": "assertive",
                },
                "tone": "technical_robust",
                "facts_style": "concrete",
                "petition_style": "prudent",
                "urgency_emphasis": "none",
                "argument_density": "high",
                "normative_quote_density": "high",
            },
            "argument_strategy": {
                "focus": "formalism",
                "risk_tolerance": "low",
                "proof_priority": ["documental"],
                "normative_anchor": "strong",
            },
        },
        jurisprudence_analysis={
            "source_quality": "real",
            "jurisprudence_strength": "strong",
            "jurisprudence_highlights": [{"case_name": "NO DEBERIA APARECER", "criterion": "x"}],
        },
        **_common_kwargs(),
    )

    titles = [section.title for section in result.sections]
    assert titles[:4] == ["Encabezado", "Riesgo Procesal y Cobertura Probatoria", "Marco Normativo", "Conclusion"]
    assert "Jurisprudencia relevante" not in titles


def test_argument_strategy_modulates_proof_and_petitum():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="el padre no paga alimentos y necesito cuota provisoria",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_directives": {
                "tone": "urgent_prudent",
                "petitum_directive": "Pedir con foco cauteloso.",
            },
            "argument_strategy": {
                "focus": "urgency",
                "risk_tolerance": "low",
                "proof_priority": ["documental", "informativa"],
                "normative_anchor": "strong",
            },
        },
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos", "forum": "familia"},
        normative_reasoning={"requirements": ["Acreditar necesidades del hijo."]},
    )

    lowered = result.full_text.lower()
    assert "prioridad sugerida: documental, informativa" in lowered or "documental" in lowered
    assert "evitar pedidos expansivos no cubiertos por la prueba" in lowered


def test_section_templates_can_force_missing_required_section_with_warning():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "jurisprudencia", "conclusion"],
                "required_sections": ["encabezado", "jurisprudencia", "conclusion"],
                "optional_sections": [],
                "section_templates": {
                    "jurisprudencia": {"required": True, "include_if_empty": True},
                },
                "content_rules": {"include_jurisprudence": "never", "normative_density": "standard", "argument_style": "prudential"},
            }
        },
        **_common_kwargs(),
    )

    assert "Jurisprudencia relevante" in [section.title for section in result.sections]
    assert any("fallback" in warning.lower() or "requerida" in warning.lower() for warning in result.warnings)


def test_include_jurisprudence_never_omits_jurisprudential_sections():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "cautela_jurisprudencial", "jurisprudencia", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["cautela_jurisprudencial", "jurisprudencia"],
                "section_templates": {},
                "content_rules": {"include_jurisprudence": "never", "normative_density": "standard", "argument_style": "prudential"},
            }
        },
        jurisprudence_analysis={
            "source_quality": "real",
            "jurisprudence_strength": "strong",
            "jurisprudence_highlights": [{"case_name": "Llampa", "criterion": "x"}],
        },
        **_common_kwargs(),
    )

    titles = [section.title for section in result.sections]
    assert "Jurisprudencia relevante" not in titles
    assert "Cautela Jurisprudencial" not in titles


def test_include_jurisprudence_always_forces_section_when_base_exists():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "jurisprudencia", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["jurisprudencia"],
                "section_templates": {"jurisprudencia": {"required": False}},
                "content_rules": {"include_jurisprudence": "always", "normative_density": "standard", "argument_style": "prudential"},
            }
        },
        jurisprudence_analysis={
            "source_quality": "real",
            "jurisprudence_strength": "strong",
            "jurisprudence_highlights": [{"case_name": "LLAMPA", "criterion": "Criterio util.", "strategic_use": "Uso.", "source_mode": "retrieved_real_precedent"}],
        },
        **_common_kwargs(),
    )

    assert "Jurisprudencia relevante" in [section.title for section in result.sections]


def test_normative_density_changes_normative_payload():
    generator = ArgumentGenerator()
    high = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload_many_norms(),
        strategy=_strategy_payload(),
        model_match={"style_blueprint": {"section_order": ["encabezado", "marco_normativo", "conclusion"], "required_sections": ["encabezado", "conclusion"], "optional_sections": ["marco_normativo"], "section_templates": {"marco_normativo": {"density": "high"}}, "content_rules": {"normative_density": "high", "include_jurisprudence": "auto", "argument_style": "prudential"}}},
        **_common_kwargs(),
    )
    low = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload_many_norms(),
        strategy=_strategy_payload(),
        model_match={"style_blueprint": {"section_order": ["encabezado", "marco_normativo", "conclusion"], "required_sections": ["encabezado", "conclusion"], "optional_sections": ["marco_normativo"], "section_templates": {"marco_normativo": {"density": "low"}}, "content_rules": {"normative_density": "low", "include_jurisprudence": "auto", "argument_style": "prudential"}}},
        **_common_kwargs(),
    )

    high_section = next(section for section in high.sections if section.title == "Marco Normativo")
    low_section = next(section for section in low.sections if section.title == "Marco Normativo")
    assert high_section.content.count("- ") > low_section.content.count("- ")


def test_argument_style_changes_analysis_wording():
    generator = ArgumentGenerator()
    assertive = generator.generate(
        query="consulta de prueba",
        mode="breve",
        reasoning=_reasoning_payload(),
        model_match={"style_blueprint": {"section_order": ["consulta", "analisis", "conclusion"], "required_sections": ["consulta", "conclusion"], "optional_sections": ["analisis"], "section_templates": {"analisis": {"style": "default"}}, "content_rules": {"argument_style": "assertive", "normative_density": "standard", "include_jurisprudence": "auto"}}},
    )
    exploratory = generator.generate(
        query="consulta de prueba",
        mode="breve",
        reasoning=_reasoning_payload(),
        model_match={"style_blueprint": {"section_order": ["consulta", "analisis", "conclusion"], "required_sections": ["consulta", "conclusion"], "optional_sections": ["analisis"], "section_templates": {"analisis": {"style": "default"}}, "content_rules": {"argument_style": "exploratory", "normative_density": "standard", "include_jurisprudence": "auto"}}},
    )

    assert "linea inicial con apoyo identificable" in assertive.full_text.lower()
    assert "exploratorio y sujeto a contraste" in exploratory.full_text.lower()


def test_strategy_focus_changes_document_priorities():
    generator = ArgumentGenerator()
    urgency = generator.generate(
        query="medida urgente",
        mode="incidente",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={"argument_strategy": {"focus": "urgency", "risk_tolerance": "medium", "proof_priority": ["documental"], "normative_anchor": "strong"}},
        facts={"requirente": "Ana", "expediente": "1/25", "juzgado": "Juzgado Civil"},
    )
    formalism = generator.generate(
        query="medida urgente",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={"argument_strategy": {"focus": "formalism", "risk_tolerance": "medium", "proof_priority": ["documental"], "normative_anchor": "strong"}},
    )

    assert "despacho preferente" in urgency.full_text.lower() or "urgencia" in urgency.full_text.lower()
    assert "encuadre normativo" in formalism.full_text.lower() or "cierre normativo" in formalism.full_text.lower()


def test_strategy_risk_tolerance_changes_closing_language():
    generator = ArgumentGenerator()
    low = generator.generate(
        query="consulta de riesgo",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        model_match={"argument_strategy": {"focus": "damage", "risk_tolerance": "low", "proof_priority": ["documental"], "normative_anchor": "strong"}},
    )
    high = generator.generate(
        query="consulta de riesgo",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        model_match={"argument_strategy": {"focus": "damage", "risk_tolerance": "high", "proof_priority": ["documental"], "normative_anchor": "strong"}},
    )

    assert "alcance deliberadamente prudente" in low.full_text.lower()
    assert "mayor intensidad" in high.full_text.lower()


def test_proof_priority_impacts_proof_section():
    generator = ArgumentGenerator()
    result = generator.generate(
        query="contestar demanda",
        mode="contestacion",
        reasoning=_reasoning_payload(),
        model_match={"argument_strategy": {"focus": "formalism", "risk_tolerance": "medium", "proof_priority": ["documental", "testimonial"], "normative_anchor": "strong"}},
        facts={
            "demandado": "Empresa SA",
            "demandante": "Juan Lopez",
            "expediente": "456/2025",
            "juzgado": "Juzgado Civil N.o 3",
            "hechos": "Niego los hechos.",
            "prueba": "Documental y testimonial.",
            "domicilio_procesal": "Belgrano 123",
        },
    )

    assert "prioridad sugerida: documental, testimonial" in result.full_text.lower()


# ---------------------------------------------------------------------------
# Pass 2: template/behavior dominance, jurisprudence bridge, warnings
# ---------------------------------------------------------------------------


def test_jurisprudence_bridge_template_overrides_profile():
    """template['include_jurisprudence'] should take priority over profile content_rules."""
    generator = ArgumentGenerator()
    # content_rules says "auto" but template says "never" → should omit
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "jurisprudencia", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["jurisprudencia"],
                "section_templates": {
                    "jurisprudencia": {"required": False, "include_jurisprudence": "never"},
                },
                "content_rules": {"include_jurisprudence": "auto", "normative_density": "standard", "argument_style": "prudential"},
            }
        },
        jurisprudence_analysis={
            "source_quality": "real",
            "jurisprudence_strength": "strong",
            "jurisprudence_highlights": [{"case_name": "LLAMPA", "criterion": "x"}],
        },
        **_common_kwargs(),
    )

    # Even though there IS jurisprudence and content_rules says "auto",
    # the per-section template override "never" should suppress it
    titles = [section.title for section in result.sections]
    assert "Jurisprudencia relevante" not in titles


def test_jurisprudence_bridge_template_always_forces_even_when_profile_says_auto():
    """template['include_jurisprudence']='always' should force section even without material."""
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "jurisprudencia", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["jurisprudencia"],
                "section_templates": {
                    "jurisprudencia": {"required": False, "include_jurisprudence": "always"},
                },
                "content_rules": {"include_jurisprudence": "auto", "normative_density": "standard", "argument_style": "prudential"},
            }
        },
        jurisprudence_analysis={},  # no material at all
        **_common_kwargs(),
    )

    # "always" should force inclusion — either real section or fallback stub
    titles = [section.title for section in result.sections]
    assert "Jurisprudencia relevante" in titles


def test_tesis_principal_uses_behavior_focus_over_profile():
    """_section_tesis_principal should read focus from behavior (strategy), not just profile."""
    generator = ArgumentGenerator()
    result = generator.generate(
        query="reclamar alimentos urgentes",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "argument_strategy": {
                "focus": "damage",
                "risk_tolerance": "medium",
                "proof_priority": ["documental"],
                "normative_anchor": "light",
            },
        },
        classification={"action_slug": "alimentos_hijos", "forum": "familia"},
    )

    lowered = result.full_text.lower()
    assert "impacto material" in lowered or "cobertura concreta" in lowered


def test_argumentos_normativos_uses_behavior_normative_anchor():
    """_section_argumentos_normativos should read normative_anchor from behavior."""
    generator = ArgumentGenerator()
    result = generator.generate(
        query="reclamo formal con anclaje fuerte",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "argument_strategy": {
                "focus": "formalism",
                "risk_tolerance": "low",
                "proof_priority": ["documental"],
                "normative_anchor": "strong",
            },
        },
        normative_reasoning={
            "requirements": ["Acreditar requisitos procesales."],
            "applied_rules": [{"source": "CCyC", "article": "438", "effect": "Exige propuesta."}],
        },
    )

    lowered = result.full_text.lower()
    assert "anclaje normativo fuerte" in lowered


def test_warnings_from_style_blueprint_propagate_to_result():
    """StyleBlueprint.warnings should appear in the final GeneratedArgument.warnings."""
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": [],  # invalid → triggers fallback warning
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": [],
                "section_templates": {},
                "content_rules": {"include_jurisprudence": "auto", "normative_density": "standard", "argument_style": "prudential"},
                "warnings": ["Blueprint warning: prueba manual de propagacion de warnings."],
            }
        },
        **_common_kwargs(),
    )

    assert any("prueba manual de propagacion de warnings" in w for w in result.warnings)


def test_dead_code_reorder_sections_by_blueprint_removed():
    """_reorder_sections_by_blueprint should no longer exist."""
    assert not hasattr(ArgumentGenerator, "_reorder_sections_by_blueprint")


# ---------------------------------------------------------------------------
# Pass 2b: per-section template overrides of strategy fields
# ---------------------------------------------------------------------------


def test_template_proof_priority_overrides_strategy():
    """section_templates['trazabilidad_probatoria']['proof_priority'] should beat argument_strategy."""
    generator = ArgumentGenerator()
    common = _common_kwargs()
    common["evidence_reasoning_links"] = {
        "summary": "Resumen de prueba.",
        "requirement_links": [
            {"requirement": "Presentar propuesta.", "support_level": "medio", "source": "CCyC", "article": "438"},
        ],
    }
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "trazabilidad_probatoria", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["trazabilidad_probatoria"],
                "section_templates": {
                    "trazabilidad_probatoria": {"proof_priority": ["testimonial", "pericial"]},
                },
                "content_rules": {"include_jurisprudence": "auto", "normative_density": "standard", "argument_style": "prudential"},
            },
            "argument_strategy": {
                "focus": "formalism",
                "risk_tolerance": "medium",
                "proof_priority": ["documental"],
                "normative_anchor": "strong",
            },
        },
        **common,
    )

    lowered = result.full_text.lower()
    # The per-section override should appear, not the global "documental"
    assert "testimonial, pericial" in lowered


def test_template_risk_tolerance_overrides_strategy():
    """section_templates['pasos_procesales']['risk_tolerance'] should beat argument_strategy."""
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "pasos_procesales", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["pasos_procesales"],
                "section_templates": {
                    "pasos_procesales": {"risk_tolerance": "low"},
                },
                "content_rules": {"include_jurisprudence": "auto", "normative_density": "standard", "argument_style": "prudential"},
            },
            "argument_strategy": {
                "focus": "formalism",
                "risk_tolerance": "high",
                "proof_priority": ["documental"],
                "normative_anchor": "strong",
            },
        },
        **_common_kwargs(),
    )

    lowered = result.full_text.lower()
    # Per-section "low" should produce the prudent language even though strategy says "high"
    assert "prudente" in lowered


def test_template_focus_overrides_strategy():
    """section_templates['analisis_juridico']['focus'] should beat argument_strategy."""
    generator = ArgumentGenerator()
    result = generator.generate(
        query="divorcio por presentacion conjunta",
        mode="formal",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["encabezado", "analisis_juridico", "conclusion"],
                "required_sections": ["encabezado", "conclusion"],
                "optional_sections": ["analisis_juridico"],
                "section_templates": {
                    "analisis_juridico": {"focus": "damage"},
                },
                "content_rules": {"include_jurisprudence": "auto", "normative_density": "standard", "argument_style": "prudential"},
            },
            "argument_strategy": {
                "focus": "formalism",
                "risk_tolerance": "medium",
                "proof_priority": ["documental"],
                "normative_anchor": "strong",
            },
        },
        **_common_kwargs(),
    )

    section = next(s for s in result.sections if s.title == "Analisis Juridico")
    # Template focus "damage" should win over strategy "formalism"
    assert "perjuicio concreto" in section.content.lower()


def test_template_normative_anchor_overrides_strategy():
    """section_templates['argumentos_normativos']['normative_anchor'] should beat argument_strategy."""
    generator = ArgumentGenerator()
    # Strategy says "light" but template says "strong" → should see strong language
    result = generator.generate(
        query="reclamo formal",
        mode="base_argumental",
        reasoning=_reasoning_payload(),
        strategy=_strategy_payload(),
        model_match={
            "style_blueprint": {
                "section_order": ["tesis_principal", "argumentos_normativos", "cierre_estrategico"],
                "required_sections": ["tesis_principal", "cierre_estrategico"],
                "optional_sections": ["argumentos_normativos"],
                "section_templates": {
                    "argumentos_normativos": {"normative_anchor": "strong"},
                },
                "content_rules": {"include_jurisprudence": "auto", "normative_density": "standard", "argument_style": "prudential"},
            },
            "argument_strategy": {
                "focus": "damage",
                "risk_tolerance": "medium",
                "proof_priority": ["documental"],
                "normative_anchor": "light",
            },
        },
        normative_reasoning={
            "requirements": ["Acreditar requisitos procesales."],
            "applied_rules": [{"source": "CCyC", "article": "438", "effect": "Exige propuesta."}],
        },
    )

    section = next(s for s in result.sections if s.title == "Argumentos Normativos")
    # Per-section "strong" should produce the anclaje fuerte line
    assert "anclaje normativo fuerte" in section.content.lower()
