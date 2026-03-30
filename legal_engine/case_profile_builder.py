"""
Case profile builder — separates case analysis from text generation.

Classification-based activation with keyword fallback.
Produces a structured, deterministic profile that the ArgumentGenerator
consumes without needing to re-derive heuristics.

Supported domains:
  - alimentos
  - conflicto_patrimonial
  - divorcio
  - regimen_comunicacional
  - cuidado_personal

Multi-domain: when a case touches more than one domain the builder runs
every matching domain builder, picks a *primary* domain via an explicit
priority list, and exposes the full list in ``case_domains``.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# Domain detection — slug map + keyword fallback
# ---------------------------------------------------------------------------

_SLUG_TO_DOMAIN: dict[str, str] = {
    "alimentos_hijos": "alimentos",
    "alimentos": "alimentos",
    "divorcio": "divorcio",
    "divorcio_vincular": "divorcio",
    "divorcio_unilateral": "divorcio",
    "regimen_comunicacional": "regimen_comunicacional",
    "regimen_visitas": "regimen_comunicacional",
    "cuidado_personal": "cuidado_personal",
    "tenencia": "cuidado_personal",
    "conflicto_patrimonial": "conflicto_patrimonial",
    "division_bienes": "conflicto_patrimonial",
    "liquidacion_sociedad_conyugal": "conflicto_patrimonial",
}

_KEYWORD_DOMAIN: list[tuple[tuple[str, ...], str]] = [
    (("alimentos", "cuota alimentaria", "cuota aliment"), "alimentos"),
    (
        (
            "divorcio", "divorciar", "disolucion del vinculo",
            "disolucion vincular", "separacion personal",
            "separarme legalmente", "separacion legal",
        ),
        "divorcio",
    ),
    (
        (
            "regimen de comunicacion", "regimen comunicacional",
            "impedimento de contacto", "contacto con el hijo",
            "contacto con la hija", "regimen de visitas",
        ),
        "regimen_comunicacional",
    ),
    (
        (
            "cuidado personal", "tenencia", "centro de vida",
            "guarda", "convivencia del hijo", "convivencia de la hija",
        ),
        "cuidado_personal",
    ),
    (
        (
            "conflicto patrimonial", "division de bienes", "bien ganancial",
            "liquidacion de la sociedad conyugal", "cotitularidad",
            "particion de bienes", "bien propio", "bien heredado",
        ),
        "conflicto_patrimonial",
    ),
]

# ---------------------------------------------------------------------------
# Domain priority — lower index = higher priority.
#
# Rationale:
#   1. alimentos — urgencia alimentaria es la pretensión más sensible
#      (art. 659+ CCyC); si aparece, gobierna la estrategia.
#   2. cuidado_personal — define con quién vive el niño; condiciona
#      régimen comunicacional y contexto de alimentos.
#   3. regimen_comunicacional — depende de la resolución del cuidado.
#   4. divorcio — es el marco procesal que contiene bienes e hijos,
#      pero no es la pretensión sustantiva principal.
#   5. conflicto_patrimonial — patrimonial puro; menor urgencia
#      personal que las anteriores.
# ---------------------------------------------------------------------------

_DOMAIN_PRIORITY: list[str] = [
    "alimentos",
    "cuidado_personal",
    "regimen_comunicacional",
    "divorcio",
    "conflicto_patrimonial",
]

# Cross-domain interaction labels used in strategic_focus when multiple
# domains are active.  Key = frozenset of two domains → focus string.
_CROSS_DOMAIN_FOCUS: dict[frozenset[str], str] = {
    frozenset({"alimentos", "cuidado_personal"}):
        "coordinar estrategia entre alimentos y cuidado personal: "
        "el esquema de cuidado incide en la cuota",
    frozenset({"alimentos", "regimen_comunicacional"}):
        "coordinar estrategia entre alimentos y regimen comunicacional: "
        "el contacto efectivo puede condicionar la obligacion alimentaria",
    frozenset({"alimentos", "divorcio"}):
        "coordinar estrategia entre alimentos y divorcio: "
        "incluir alimentos en la propuesta reguladora",
    frozenset({"divorcio", "conflicto_patrimonial"}):
        "coordinar estrategia entre divorcio y conflicto patrimonial: "
        "resolver regimen de bienes dentro del proceso de divorcio",
    frozenset({"divorcio", "cuidado_personal"}):
        "coordinar estrategia entre divorcio y cuidado personal: "
        "definir cuidado personal en la propuesta reguladora",
    frozenset({"divorcio", "regimen_comunicacional"}):
        "coordinar estrategia entre divorcio y regimen comunicacional: "
        "incluir regimen de comunicacion en la propuesta reguladora",
    frozenset({"cuidado_personal", "regimen_comunicacional"}):
        "coordinar estrategia entre cuidado personal y regimen comunicacional: "
        "el esquema de cuidado define el regimen de contacto",
    frozenset({"alimentos", "conflicto_patrimonial"}):
        "coordinar estrategia entre alimentos y conflicto patrimonial: "
        "la capacidad contributiva puede depender de la resolucion patrimonial",
    frozenset({"cuidado_personal", "conflicto_patrimonial"}):
        "coordinar estrategia entre cuidado personal y conflicto patrimonial: "
        "la vivienda del nino puede depender de la adjudicacion del inmueble",
    frozenset({"regimen_comunicacional", "conflicto_patrimonial"}):
        "coordinar estrategia entre regimen comunicacional y conflicto patrimonial: "
        "el acceso al hogar puede incidir en el contacto",
}


def _detect_domains(action_slug: str, text: str, *, query_text: str = "") -> list[str]:
    """Return *all* matching domains, ordered by ``_DOMAIN_PRIORITY``.

    When the *query itself* contains an explicit divorce intent signal,
    divorcio is forced to the first position regardless of priority
    ordering — the user's nuclear intention overrides the default
    urgency-based ranking.
    """
    found: set[str] = set()

    slug = action_slug.strip()
    if slug and slug in _SLUG_TO_DOMAIN:
        found.add(_SLUG_TO_DOMAIN[slug])

    for keywords, domain in _KEYWORD_DOMAIN:
        if any(kw in text for kw in keywords):
            found.add(domain)

    priority_index = {d: i for i, d in enumerate(_DOMAIN_PRIORITY)}
    sorted_domains = sorted(found, key=lambda d: priority_index.get(d, 999))

    # --- Explicit divorce intent override ---
    # If the user's own query expresses direct divorce intention, force
    # divorcio as primary.  Secondary domains remain but cannot displace it.
    if "divorcio" in sorted_domains and _query_has_explicit_divorce_intent(query_text):
        sorted_domains = ["divorcio"] + [d for d in sorted_domains if d != "divorcio"]

    return sorted_domains


# Patterns that unambiguously express "I want a divorce" in the user query.
_EXPLICIT_DIVORCE_INTENT: tuple[str, ...] = (
    "quiero divorciarme",
    "me quiero divorciar",
    "quiero el divorcio",
    "iniciar divorcio",
    "iniciar el divorcio",
    "pedir divorcio",
    "pedir el divorcio",
    "tramitar divorcio",
    "tramitar el divorcio",
    "separarme legalmente",
    "separacion legal",
    "divorcio vincular",
    "disolucion del vinculo",
)


def _query_has_explicit_divorce_intent(query_text: str) -> bool:
    """Return True if the normalized *query* (not enriched text) expresses
    direct divorce intent.  A bare mention of 'divorcio' as the sole
    meaningful token also qualifies (e.g. the user typed just 'divorcio').
    """
    if not query_text:
        return False
    q = query_text.strip()
    # Bare single-word 'divorcio'
    if q in ("divorcio", "divorciarse", "divorciarme"):
        return True
    return any(pattern in q for pattern in _EXPLICIT_DIVORCE_INTENT)


# ---------------------------------------------------------------------------
# Downstream alignment: action_slug ↔ case_domain
# ---------------------------------------------------------------------------

# Canonical slug per domain family — used when an action_slug needs correction.
_DOMAIN_TO_CANONICAL_SLUG: dict[str, str] = {
    "divorcio": "divorcio_unilateral",
    "alimentos": "alimentos_hijos",
    "cuidado_personal": "cuidado_personal",
    "regimen_comunicacional": "regimen_comunicacional",
    "conflicto_patrimonial": "conflicto_patrimonial",
}


def align_classification_with_domain(
    classification: dict[str, Any],
    case_domain: str | None,
    query: str,
) -> dict[str, Any]:
    """Ensure action_slug is consistent with case_domain when explicit intent
    forced a domain override.

    Returns a *new* classification dict (shallow copy) if correction was
    needed, or the original if already aligned.

    Only corrects when ALL of the following hold:
      1. case_domain is set and differs from the slug's domain family.
      2. The user's query contains explicit intent for the winning domain.
      3. The slug maps to a different domain family.

    This prevents downstream consumers (model_library, argument generator)
    from operating on a stale slug while case_domain has already been
    corrected by the domain-priority override.
    """
    if not case_domain:
        return classification

    action_slug = str(classification.get("action_slug") or "").strip()
    slug_domain = _SLUG_TO_DOMAIN.get(action_slug)

    # Already aligned — nothing to do.
    if slug_domain == case_domain:
        return classification

    # Only override if the user expressed explicit intent for the winning
    # domain.  Currently only divorce-override is implemented; extend the
    # check here if other domains need similar treatment.
    query_text = _normalize_text(query)
    needs_override = False
    if case_domain == "divorcio" and _query_has_explicit_divorce_intent(query_text):
        needs_override = True

    if not needs_override:
        return classification

    canonical_slug = _DOMAIN_TO_CANONICAL_SLUG.get(case_domain)
    if not canonical_slug:
        return classification

    corrected = dict(classification)
    corrected["action_slug"] = canonical_slug
    corrected["_original_action_slug"] = action_slug
    corrected["_slug_aligned_to_domain"] = case_domain
    return corrected


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_case_profile(
    query: str,
    classification: dict[str, Any],
    case_theory: dict[str, Any],
    conflict: dict[str, Any],
    normative_reasoning: dict[str, Any],
    procedural_plan: Any | None,
    facts: dict[str, str],
) -> dict[str, Any]:
    """Build a structured case profile from pipeline inputs.

    Returns a dict with:
      - case_domain: str | None          (primary domain)
      - case_domains: list[str]          (all detected domains, priority-ordered)
      - is_alimentos: bool               (backward compat)
      - scenarios: set[str]              (from primary domain builder)
      - urgency_level: "high" | "medium" | "low"
      - vulnerability: bool
      - needs_proof_strengthening: bool
      - strategic_focus: list[str]
    """
    action_slug = str(classification.get("action_slug") or "").strip()
    query_text = _normalize_text(query)
    text = _collect_text(
        query, classification, case_theory, conflict,
        normative_reasoning, procedural_plan, facts,
    )

    domains = _detect_domains(action_slug, text, query_text=query_text)
    if not domains:
        return _empty_profile()

    primary = domains[0]
    builder = _DOMAIN_BUILDERS.get(primary)
    if builder is None:
        return _empty_profile()

    profile = builder(
        text=text,
        query_text=query_text,
        normative_reasoning=normative_reasoning,
    )

    # Inject multi-domain fields
    profile["case_domains"] = domains
    profile["input_facts"] = dict(facts or {})

    # Add cross-domain strategic focus when multiple domains are present
    if len(domains) > 1:
        _add_cross_domain_focus(profile, domains)

    return profile


# ---------------------------------------------------------------------------
# Domain builders
# ---------------------------------------------------------------------------

def _build_alimentos(
    *, text: str, query_text: str, normative_reasoning: dict[str, Any],
) -> dict[str, Any]:
    articles = {
        str(item.get("article") or "").strip()
        for item in (normative_reasoning.get("applied_rules") or [])
        if isinstance(item, dict)
    }

    scenarios: set[str] = set()

    if any(token in text for token in (
        "no paga", "incumpl", "mora", "deuda",
        "pagos parciales", "sin aportes",
    )):
        scenarios.add("incumplimiento")

    if any(token in text for token in (
        "provisoria", "provisorios", "cuota provisoria",
    )):
        scenarios.add("cuota_provisoria")

    if any(token in text for token in (
        "abuelo", "abuela", "abuelos", "ascend",
        "subsidiar", "obligado principal", "progenitor imposibilitado",
    )):
        scenarios.add("ascendientes")

    age_data = _extract_age_features(text)
    studies_positive = any(token in query_text for token in (
        "estudia", "estudiando", "estudiante", "universit",
        "alumno regular", "regularidad academica",
    ))
    studies_negative = any(token in query_text for token in (
        "no estudia", "dejo de estudiar", "ya no estudia",
    ))
    works_or_has_income = any(token in query_text for token in (
        "trabaja", "trabajando", "ingresos propios", "cobra sueldo",
    ))
    no_work = any(token in query_text for token in (
        "no trabaja", "desocupado", "desocupada", "sin empleo", "no tiene trabajo",
    ))
    cohabits = any(token in query_text for token in (
        "convive", "vive conmigo", "vive con la madre", "vive con su mama", "vive con su padre",
    ))

    if age_data["has_minor"]:
        scenarios.add("hijo_menor")
    if age_data["has_18_21"]:
        scenarios.add("hijo_18_21")
    if "663" in articles or studies_positive or "hijo mayor" in text:
        scenarios.add("hijo_mayor")
    if age_data["has_over_21"] and studies_negative:
        scenarios.add("hijo_mayor_no_estudia")
    elif age_data["has_over_21"] and (studies_positive or "663" in articles):
        scenarios.add("hijo_mayor")
        scenarios.add("hijo_mayor_estudiante")
    elif not studies_negative and ("663" in articles or studies_positive):
        scenarios.add("hijo_mayor_estudiante")

    if "conyuge" in text or "esposa" in text or "esposo" in text:
        scenarios.add("mixto_conyuge")

    if any(token in text for token in (
        "vivienda", "alquiler", "habitacion", "techo",
    )):
        scenarios.add("vivienda")

    # vulnerability
    vulnerability = _detect_vulnerability(text)

    # urgency
    urgent = (
        any(token in text for token in (
            "urgencia", "embargo", "retencion", "feria",
            "habilitacion", "dia y hora", "medida cautelar",
        ))
        or "cuota_provisoria" in scenarios
    )
    urgency_level = "high" if urgent else ("medium" if scenarios else "low")

    # proof strengthening
    needs_proof = (
        bool(scenarios & {"cuota_provisoria", "incumplimiento", "ascendientes", "hijo_mayor"})
        or vulnerability
    )

    # strategic focus
    focus: list[str] = []
    if "incumplimiento" in scenarios:
        focus.append("acreditar incumplimiento alimentario")
    if "cuota_provisoria" in scenarios:
        focus.append("sostener cuota provisoria con prueba concreta")
    if vulnerability:
        focus.append("proteccion reforzada y acceso a justicia")
    if "ascendientes" in scenarios:
        focus.append("subsidiariedad y prueba de imposibilidad del obligado principal")
    if "hijo_mayor_estudiante" in scenarios:
        focus.append("diferenciar alimentos de hijo mayor estudiante")
    elif "hijo_mayor_no_estudia" in scenarios:
        focus.append("bloquear estrategias de hijo mayor estudiante incompatibles con no estudia")
    elif "hijo_18_21" in scenarios:
        focus.append("separar el tramo 18 a 21 del supuesto de hijo mayor estudiante")
    elif "hijo_menor" in scenarios:
        focus.append("mantener el supuesto de hijo menor sin mezclarlo con hijo mayor")
    if "mixto_conyuge" in scenarios:
        focus.append("separar rubros de hijos y conyuge")
    if "vivienda" in scenarios:
        focus.append("incluir componente habitacional")
    if cohabits:
        focus.append("usar convivencia como dato de gastos y cuidado cotidiano")
    if works_or_has_income:
        focus.append("verificar autonomia economica antes de sostener continuidad o aumento")
    if no_work:
        focus.append("si no trabaja, no asumir autosustento por edad sola; exigir dato real de ingresos")

    return _make_profile(
        domain="alimentos",
        is_alimentos=True,
        scenarios=scenarios,
        urgency_level=urgency_level,
        vulnerability=vulnerability,
        needs_proof=needs_proof,
        focus=focus,
    )


def _build_conflicto_patrimonial(
    *, text: str, query_text: str, normative_reasoning: dict[str, Any],
) -> dict[str, Any]:
    scenarios: set[str] = set()

    # cotitularidad
    if any(token in text for token in (
        "cotitular", "copropie", "condominio", "titularidad conjunta",
    )):
        scenarios.add("cotitularidad")

    # bien ganancial / propio / heredado
    if any(token in text for token in ("ganancial", "sociedad conyugal")):
        scenarios.add("bien_ganancial")
    if any(token in text for token in ("bien propio", "bien personal")):
        scenarios.add("bien_propio")
    if any(token in text for token in ("herencia", "heredado", "sucesorio")):
        scenarios.add("bien_heredado")

    # conflicto vs acuerdo
    if any(token in text for token in (
        "acuerdo", "convenio", "liquidacion consensuada", "particion amigable",
    )):
        scenarios.add("acuerdo")
    if any(token in text for token in (
        "conflicto", "disputa", "oposicion", "no hay acuerdo",
        "desacuerdo", "sin acuerdo", "unilateral",
    )):
        scenarios.add("conflicto")

    # liquidacion
    if any(token in text for token in (
        "liquidacion", "particion", "division de bienes", "adjudicacion",
    )):
        scenarios.add("liquidacion")

    # inmueble
    if any(token in text for token in (
        "inmueble", "propiedad", "departamento", "casa", "terreno", "lote",
    )):
        scenarios.add("inmueble")

    vulnerability = _detect_vulnerability(text)

    urgent = any(token in text for token in (
        "urgencia", "medida cautelar", "inhibicion", "embargo",
        "anotacion de litis", "venta inminente", "enajenacion",
    ))
    urgency_level = "high" if urgent else ("medium" if scenarios else "low")

    needs_proof = bool(
        scenarios & {"cotitularidad", "bien_ganancial", "bien_heredado", "conflicto"}
    ) or vulnerability

    focus: list[str] = []
    if "cotitularidad" in scenarios:
        focus.append("acreditar cotitularidad o condominio sobre el bien")
    if "bien_ganancial" in scenarios:
        focus.append("determinar caracter ganancial y regimen de liquidacion aplicable")
    if "bien_propio" in scenarios:
        focus.append("probar caracter propio del bien con titulo o causa de adquisicion")
    if "bien_heredado" in scenarios:
        focus.append("vincular el bien a la sucesion y definir porcion hereditaria")
    if "conflicto" in scenarios:
        focus.append("plantear la controversia patrimonial y la pretension concreta")
    if "acuerdo" in scenarios:
        focus.append("verificar alcance y validez del acuerdo de particion")
    if "liquidacion" in scenarios:
        focus.append("ordenar inventario, valuacion y criterio de adjudicacion")
    if "inmueble" in scenarios:
        focus.append("individualizar inmueble con datos registrales y estado ocupacional")
    if vulnerability:
        focus.append("proteccion reforzada y acceso a justicia")

    return _make_profile(
        domain="conflicto_patrimonial",
        is_alimentos=False,
        scenarios=scenarios,
        urgency_level=urgency_level,
        vulnerability=vulnerability,
        needs_proof=needs_proof,
        focus=focus,
    )


def _build_divorcio(
    *, text: str, query_text: str, normative_reasoning: dict[str, Any],
) -> dict[str, Any]:
    scenarios: set[str] = set()

    # unilateral vs conjunto
    if any(token in text for token in (
        "unilateral", "peticion unilateral", "voluntad unilateral",
    )):
        scenarios.add("unilateral")
    if any(token in text for token in (
        "conjunto", "presentacion conjunta", "mutuo acuerdo",
        "de comun acuerdo",
    )):
        scenarios.add("conjunto")
    # if neither detected, default to unilateral (CCyC 437)
    if not (scenarios & {"unilateral", "conjunto"}):
        scenarios.add("unilateral")

    # bienes
    if any(token in text for token in (
        "bienes", "ganancial", "liquidacion", "particion",
        "sociedad conyugal", "bien inmueble",
    )):
        scenarios.add("bienes")

    # hijos
    if any(token in text for token in (
        "hijo", "hija", "hijos", "menor", "menores",
        "progenitor", "alimentos", "cuidado personal",
        "regimen comunicacional",
    )):
        scenarios.add("hijos")

    # convenio regulador
    if any(token in text for token in (
        "convenio regulador", "propuesta reguladora", "convenio",
    )):
        scenarios.add("convenio_regulador")

    # violencia / urgencia
    if any(token in text for token in ("violencia", "restriccion", "exclusion del hogar")):
        scenarios.add("violencia")

    vulnerability = _detect_vulnerability(text)

    urgent = (
        "violencia" in scenarios
        or any(token in text for token in (
            "urgencia", "medida cautelar", "exclusion del hogar",
            "medida de proteccion",
        ))
    )
    urgency_level = "high" if urgent else ("medium" if scenarios else "low")

    needs_proof = bool(scenarios & {"bienes", "hijos", "violencia"}) or vulnerability

    focus: list[str] = []
    if "unilateral" in scenarios:
        focus.append("armar presentacion unilateral con propuesta reguladora (art. 438 CCyC)")
    if "conjunto" in scenarios:
        focus.append("verificar convenio regulador conjunto y su contenido minimo")
    if "bienes" in scenarios:
        focus.append("incluir regimen patrimonial y propuesta de liquidacion")
    if "hijos" in scenarios:
        focus.append("resolver situacion de hijos: cuidado personal, alimentos y comunicacion")
    if "convenio_regulador" in scenarios:
        focus.append("revisar completitud del convenio regulador")
    if "violencia" in scenarios:
        focus.append("priorizar medidas de proteccion y exclusion del hogar")
    if vulnerability:
        focus.append("proteccion reforzada y acceso a justicia")

    return _make_profile(
        domain="divorcio",
        is_alimentos=False,
        scenarios=scenarios,
        urgency_level=urgency_level,
        vulnerability=vulnerability,
        needs_proof=needs_proof,
        focus=focus,
    )


def _build_regimen_comunicacional(
    *, text: str, query_text: str, normative_reasoning: dict[str, Any],
) -> dict[str, Any]:
    scenarios: set[str] = set()

    # impedimento de contacto
    if any(token in text for token in (
        "impedimento", "obstruccion", "no deja ver",
        "no permite contacto", "impide el contacto",
        "niega el contacto", "retiene al hijo", "retiene a la hija",
    )):
        scenarios.add("impedimento_contacto")

    # revinculacion
    if any(token in text for token in (
        "revinculacion", "retomar contacto", "reconstruir vinculo",
        "tiempo sin ver",
    )):
        scenarios.add("revinculacion")

    # ampliacion / modificacion
    if any(token in text for token in (
        "ampliar", "ampliacion", "modificar", "modificacion",
        "cambiar regimen", "mas tiempo",
    )):
        scenarios.add("modificacion")

    # fijacion inicial
    if any(token in text for token in (
        "fijar regimen", "establecer regimen", "sin regimen",
        "no hay regimen", "primera vez",
    )):
        scenarios.add("fijacion")

    # pernocte / vacaciones
    if any(token in text for token in ("pernocte", "pernoctar")):
        scenarios.add("pernocte")
    if any(token in text for token in ("vacaciones", "feriados", "receso")):
        scenarios.add("vacaciones")

    vulnerability = _detect_vulnerability(text)

    urgent = (
        "impedimento_contacto" in scenarios
        or any(token in text for token in (
            "urgencia", "medida cautelar", "audiencia inmediata",
            "dia y hora", "retencion indebida",
        ))
    )
    urgency_level = "high" if urgent else ("medium" if scenarios else "low")

    needs_proof = bool(
        scenarios & {"impedimento_contacto", "revinculacion"}
    ) or vulnerability

    focus: list[str] = []
    if "impedimento_contacto" in scenarios:
        focus.append("acreditar impedimento de contacto con prueba concreta")
    if "revinculacion" in scenarios:
        focus.append("plantear revinculacion progresiva con eventual intervencion de equipo tecnico")
    if "modificacion" in scenarios:
        focus.append("justificar modificacion del regimen con cambio de circunstancias")
    if "fijacion" in scenarios:
        focus.append("fijar regimen comunicacional con esquema concreto de dias, horarios y modalidad")
    if "pernocte" in scenarios:
        focus.append("incluir pernocte en el regimen propuesto")
    if "vacaciones" in scenarios:
        focus.append("prever distribucion de vacaciones y feriados")
    if vulnerability:
        focus.append("proteccion reforzada y acceso a justicia")
    if urgent and "impedimento_contacto" in scenarios:
        focus.append("solicitar audiencia inmediata o medida cautelar de contacto")

    return _make_profile(
        domain="regimen_comunicacional",
        is_alimentos=False,
        scenarios=scenarios,
        urgency_level=urgency_level,
        vulnerability=vulnerability,
        needs_proof=needs_proof,
        focus=focus,
    )


def _build_cuidado_personal(
    *, text: str, query_text: str, normative_reasoning: dict[str, Any],
) -> dict[str, Any]:
    scenarios: set[str] = set()

    # centro de vida
    if any(token in text for token in (
        "centro de vida", "residencia habitual", "lugar donde vive",
    )):
        scenarios.add("centro_de_vida")

    # convivencia actual
    if any(token in text for token in (
        "convive con", "vive con", "convivencia actual",
        "a cargo de", "bajo cuidado de",
    )):
        scenarios.add("convivencia_actual")

    # modalidad
    if any(token in text for token in (
        "cuidado compartido", "cuidado alternado", "tenencia compartida",
        "compartido", "alternado",
    )):
        scenarios.add("cuidado_compartido")
    if any(token in text for token in (
        "cuidado unipersonal", "tenencia exclusiva", "cuidado exclusivo",
    )):
        scenarios.add("cuidado_unipersonal")

    # interes superior
    if any(token in text for token in (
        "interes superior", "interes del nino", "interes de la nina",
        "derecho del nino", "convencion del nino",
    )):
        scenarios.add("interes_superior")

    # cambio de cuidado / traslado
    if any(token in text for token in (
        "cambio de cuidado", "cambio de tenencia", "modificar cuidado",
        "traslado", "mudanza", "cambio de domicilio",
    )):
        scenarios.add("cambio_cuidado")

    # riesgo
    if any(token in text for token in (
        "riesgo", "desproteccion", "abandono", "negligencia", "maltrato",
    )):
        scenarios.add("riesgo")

    vulnerability = _detect_vulnerability(text)

    urgent = (
        "riesgo" in scenarios
        or any(token in text for token in (
            "urgencia", "medida cautelar", "medida de proteccion",
            "guarda provisoria", "peligro",
        ))
    )
    urgency_level = "high" if urgent else ("medium" if scenarios else "low")

    needs_proof = bool(
        scenarios & {"cambio_cuidado", "riesgo", "cuidado_unipersonal"}
    ) or vulnerability

    focus: list[str] = []
    if "centro_de_vida" in scenarios:
        focus.append("acreditar centro de vida del nino con prueba de arraigo y continuidad")
    if "convivencia_actual" in scenarios:
        focus.append("describir esquema actual de convivencia y cuidado cotidiano")
    if "cuidado_compartido" in scenarios:
        focus.append("fundamentar viabilidad del cuidado compartido con plan concreto")
    if "cuidado_unipersonal" in scenarios:
        focus.append("justificar cuidado unipersonal con razones de interes superior")
    if "interes_superior" in scenarios:
        focus.append("centrar argumentacion en interes superior del nino como principio rector")
    if "cambio_cuidado" in scenarios:
        focus.append("acreditar cambio de circunstancias que justifique modificar el cuidado")
    if "riesgo" in scenarios:
        focus.append("documentar situacion de riesgo y solicitar medida de proteccion urgente")
    if vulnerability:
        focus.append("proteccion reforzada y acceso a justicia")

    return _make_profile(
        domain="cuidado_personal",
        is_alimentos=False,
        scenarios=scenarios,
        urgency_level=urgency_level,
        vulnerability=vulnerability,
        needs_proof=needs_proof,
        focus=focus,
    )


# ---------------------------------------------------------------------------
# Domain registry
# ---------------------------------------------------------------------------

_DOMAIN_BUILDERS: dict[str, Any] = {
    "alimentos": _build_alimentos,
    "conflicto_patrimonial": _build_conflicto_patrimonial,
    "divorcio": _build_divorcio,
    "regimen_comunicacional": _build_regimen_comunicacional,
    "cuidado_personal": _build_cuidado_personal,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_profile(
    *,
    domain: str,
    is_alimentos: bool,
    scenarios: set[str],
    urgency_level: str,
    vulnerability: bool,
    needs_proof: bool,
    focus: list[str],
) -> dict[str, Any]:
    return {
        "case_domain": domain,
        "case_domains": [domain],  # overwritten by build_case_profile
        "is_alimentos": is_alimentos,
        "scenarios": scenarios,
        "urgency_level": urgency_level,
        "vulnerability": vulnerability,
        "needs_proof_strengthening": needs_proof,
        "strategic_focus": focus,
    }


def _empty_profile() -> dict[str, Any]:
    return {
        "case_domain": None,
        "case_domains": [],
        "is_alimentos": False,
        "scenarios": set(),
        "urgency_level": "low",
        "vulnerability": False,
        "needs_proof_strengthening": False,
        "strategic_focus": [],
        "input_facts": {},
    }


def _add_cross_domain_focus(profile: dict[str, Any], domains: list[str]) -> None:
    """Append cross-domain coordination entries to strategic_focus."""
    focus = profile["strategic_focus"]
    seen: set[frozenset[str]] = set()
    for i, d1 in enumerate(domains):
        for d2 in domains[i + 1:]:
            pair = frozenset({d1, d2})
            if pair not in seen:
                seen.add(pair)
                label = _CROSS_DOMAIN_FOCUS.get(pair)
                if label:
                    focus.append(label)


def _detect_vulnerability(text: str) -> bool:
    return any(token in text for token in (
        "violencia", "vulnerab", "bajos recursos", "sin recursos",
        "defensoria", "anses", "auh", "cbu", "smvm",
    ))


def _collect_text(
    query: str,
    classification: dict[str, Any],
    case_theory: dict[str, Any],
    conflict: dict[str, Any],
    normative_reasoning: dict[str, Any],
    procedural_plan: Any | None,
    facts: dict[str, str],
) -> str:
    parts = [
        query,
        str(classification.get("action_slug") or ""),
        classification.get("action_label"),
        conflict.get("core_dispute"),
        conflict.get("most_vulnerable_point"),
        conflict.get("strongest_point"),
        case_theory.get("primary_theory"),
        case_theory.get("objective"),
        " ".join(str(x) for x in case_theory.get("likely_points_of_conflict") or []),
        " ".join(str(x) for x in case_theory.get("evidentiary_needs") or []),
        " ".join(str(x) for x in normative_reasoning.get("requirements") or []),
        " ".join(str(x) for x in normative_reasoning.get("inferences") or []),
        " ".join(str(x) for x in (getattr(procedural_plan, "risks", None) or [])),
        " ".join(str(x) for x in (getattr(procedural_plan, "missing_info", None) or [])),
        " ".join(str(v) for v in facts.values()),
    ]
    raw = " ".join(str(x or "") for x in parts)
    return _normalize_text(raw)


def _extract_age_features(text: str) -> dict[str, bool]:
    ages = [int(match) for match in re.findall(r"\b\d{1,2}\b", text)]
    return {
        "has_minor": any(age < 18 for age in ages),
        "has_18_21": any(18 <= age <= 21 for age in ages),
        "has_over_21": any(age > 21 for age in ages),
    }


def _normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(char for char in nfkd if not unicodedata.combining(char))
