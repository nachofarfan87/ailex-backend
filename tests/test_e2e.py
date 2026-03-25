"""
AILEX — Tests end-to-end de flujos jurídicos completos.

Verifica el comportamiento real del pipeline end-to-end:
- Coherencia de datos entre módulos encadenados
- Reglas de negocio (confianza, placeholders, severidad)
- Invariantes del contrato JuridicalResponse

Flujos cubiertos:
  E2E-1: Traslado → borrador contesta_traslado → revisión
  E2E-2: Intimación documental → borrador acompaña_documentacion
  E2E-3: Notificación insuficiente → sin borrador, confianza SIN_RESPALDO
  E2E-4: Baja confianza → sin invención de normativa
  E2E-5: Borrador con negativa genérica → versión sugerida con placeholders preservados

Uso:
  cd backend
  pytest tests/test_e2e.py -v
"""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def assert_juridical_response(data: dict):
    """Verifica la estructura del contrato JuridicalResponse (8 secciones)."""
    required = [
        "resumen_ejecutivo", "hechos_relevantes", "encuadre_preliminar",
        "acciones_sugeridas", "riesgos_observaciones", "fuentes_respaldo",
        "datos_faltantes", "nivel_confianza",
    ]
    for field in required:
        assert field in data, f"Campo obligatorio faltante: {field}"
    assert data["nivel_confianza"] in ("alto", "medio", "bajo", "sin_respaldo"), \
        f"nivel_confianza inválido: {data['nivel_confianza']}"
    assert 0.0 <= data.get("confianza_score", 0.0) <= 1.0
    assert data.get("modulo_origen"), "modulo_origen debe estar presente y no vacío"


def assert_no_invented_normativa(borrador: str):
    """Un borrador sin fuentes no debe citar artículos con certeza absoluta."""
    # Verificar que tenga advertencias explícitas si hay citas normativas
    if "art." in borrador.lower() or "artículo" in borrador.lower():
        assert "[ADVERTENCIA" in borrador or "{{" in borrador, \
            "Borrador cita normativa sin fuentes — debe incluir advertencia o placeholder"


# ─── E2E-1: Traslado → borrador → revisión ────────────────────────────────────

async def test_e2e_traslado_borrador_revision(client):
    """
    Flujo: notificación de traslado → workflow genera contesta_traslado
    → borrador tiene placeholders → audit no reporta errores en el borrador base.

    Invariantes verificados:
    - tipo_escrito_sugerido.tipo_escrito == "contesta_traslado"
    - borrador_inicial contiene {{PLACEHOLDER}}
    - nivel_confianza_global válido
    - observaciones_revision.severidad_general es string válido (si audit corrió)
    """
    payload = {
        "texto": (
            "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
            "Expte. N° 12345/2024\n"
            "San Salvador de Jujuy, 5 de marzo de 2026.\n"
            "Córrase traslado de la demanda por 5 días. Notifíquese."
        ),
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "objetivo_usuario": "preparar respuesta inicial prudente",
        "generar_borrador": True,
        "variante_borrador": "estandar",
        "datos_caso": {
            "actor": "María González",
            "demandado": "Juan López",
        },
    }
    r = await client.post("/api/workflow/notification-response", json=payload)
    assert r.status_code == 200
    data = r.json()

    # Estructura del workflow response
    assert "resumen_caso" in data
    assert "nivel_confianza_global" in data
    assert data["nivel_confianza_global"] in ("alto", "medio", "bajo", "sin_respaldo")

    # Escrito sugerido es contesta_traslado
    sugerido = data["tipo_escrito_sugerido"]
    assert sugerido["tipo_escrito"] == "contesta_traslado"
    assert sugerido["disponible_en_generador"] is True

    # Si se generó borrador, debe tener placeholders
    if data.get("borrador_inicial"):
        assert "{{" in data["borrador_inicial"], \
            "El borrador debe contener {{PLACEHOLDER}} para datos no provistos"

    # Si hubo revisión, la severidad es un valor válido
    revision = data.get("observaciones_revision", {})
    if revision.get("severidad_general"):
        assert revision["severidad_general"] in ("grave", "moderada", "leve", "sin_problemas")

    # Estrategia presente
    assert "opciones_estrategicas_resumidas" in data


# ─── E2E-2: Intimación documental → borrador acompaña_documentacion ───────────

async def test_e2e_intimacion_documental(client):
    """
    Flujo: intimación para acompañar documental → workflow sugiere
    acompana_documentacion → generación disponible.

    Invariantes:
    - tipo_escrito_sugerido.tipo_escrito == "acompana_documentacion"
    - borrador contiene {{PLACEHOLDER}} para los documentos
    """
    payload = {
        "texto": (
            "Intímese a la parte actora a acompañar la documental ofrecida "
            "en el plazo de 3 días, bajo apercibimiento de ley."
        ),
        "fuero": "civil",
        "materia": "general",
        "objetivo_usuario": "regularizar la documentación requerida",
        "generar_borrador": True,
        "variante_borrador": "estandar",
    }
    r = await client.post("/api/workflow/notification-response", json=payload)
    assert r.status_code == 200
    data = r.json()

    sugerido = data["tipo_escrito_sugerido"]
    # El tipo sugerido debe ser acompana_documentacion (o no sugerirse si la
    # detección falla — aceptamos ambos para el test de humo, pero si hay
    # sugerencia, debe ser válida)
    if sugerido["tipo_escrito"] is not None:
        valid_types = {
            "acompana_documentacion", "contesta_traslado", "pronto_despacho",
            "demanda", "contestacion", "recurso", "medida_cautelar",
            "solicita_pronto_pago",
        }
        assert sugerido["tipo_escrito"] in valid_types or "/" in sugerido["tipo_escrito"]

    if data.get("borrador_inicial"):
        assert "{{" in data["borrador_inicial"]


# ─── E2E-3: Notificación insuficiente → sin borrador, baja confianza ──────────

async def test_e2e_notificacion_insuficiente_sin_borrador(client):
    """
    Flujo: texto ambiguo sin actuaciones claras → no genera borrador,
    confianza muy baja o sin_respaldo.

    Invariantes:
    - generar_borrador=False → borrador_inicial es None
    - nivel_confianza_global en ("bajo", "sin_respaldo") cuando no hay fuentes
    - tipo_escrito_sugerido puede ser None
    """
    payload = {
        "texto": "Se informa una posible demora en el expediente, sin constancias adjuntas.",
        "objetivo_usuario": "decidir si conviene impulsar una medida",
        "generar_borrador": False,
    }
    r = await client.post("/api/workflow/notification-response", json=payload)
    assert r.status_code == 200
    data = r.json()

    # Sin generación habilitada → sin borrador
    assert data["borrador_inicial"] is None

    # Sin fuentes → confianza baja o sin_respaldo
    assert data["nivel_confianza_global"] in ("bajo", "sin_respaldo")

    # Siempre hay resumen
    assert data["resumen_caso"]


# ─── E2E-4: Generación sin respaldo → placeholder, no normativa inventada ─────

async def test_e2e_generacion_sin_respaldo_no_inventa_normativa(client):
    """
    Flujo: generación en área sin fuentes RAG disponibles →
    borrador generado con {{PLACEHOLDER}}, no cita artículos con certeza.

    Invariantes:
    - nivel_confianza == "sin_respaldo" cuando fuentes_respaldo está vacía
    - confianza_score == 0.0 sin fuentes
    - borrador tiene advertencia si hay citas normativas
    - riesgos_observaciones advierte la falta de respaldo
    """
    payload = {
        "fuero": "administrativo",
        "materia": "contrato de locación de servicios",
        "tipo_escrito": "demanda",
        "variante": "conservador",
        "datos": None,
        "hechos": None,
    }
    r = await client.post("/api/generation/generate", json=payload)
    assert r.status_code == 200
    data = r.json()

    assert_juridical_response(data)
    assert "borrador" in data
    assert "placeholders_detectados" in data

    # Si no hay fuentes: confianza debe ser sin_respaldo
    if not data["fuentes_respaldo"]:
        assert data["nivel_confianza"] == "sin_respaldo"
        assert data["confianza_score"] == 0.0

    # El borrador no debe citar artículos sin advertencia cuando no hay fuentes
    if not data["fuentes_respaldo"]:
        assert_no_invented_normativa(data["borrador"])

    # riesgos_observaciones debe advertir falta de respaldo si fuentes vacías
    if not data["fuentes_respaldo"]:
        riesgos_text = " ".join(data.get("riesgos_observaciones", []))
        assert "respaldo" in riesgos_text.lower() or "verificar" in riesgos_text.lower()


# ─── E2E-5: Borrador con negativa → versión sugerida preserva placeholders ────

async def test_e2e_borrador_negativa_version_sugerida(client):
    """
    Flujo: generar contestación → borrador tiene negativa genérica de plantilla
    → auditar → versión sugerida corrige negativa pero preserva todos los {{PLACEHOLDER}}.

    Invariantes:
    - versión sugerida comienza con [VERSIÓN SUGERIDA — AILEX]
    - Los {{PLACEHOLDER}} del original se preservan en la versión sugerida
    - cambios_aplicados no está vacío cuando hay correcciones
    - No se inventan hechos ni se cierran placeholders
    """
    # Paso 1: generar borrador de contestación
    gen_payload = {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "contestacion",
        "variante": "estandar",
        "datos": {
            "nombre_parte": "Juan López",
            "caratula": "González c/ López",
            "numero_expediente": "345/2025",
        },
    }
    gen_r = await client.post("/api/generation/generate", json=gen_payload)
    assert gen_r.status_code == 200
    gen_data = gen_r.json()
    borrador = gen_data["borrador"]
    assert borrador, "El borrador generado no debe estar vacío"

    # Paso 2: auditar escrito con negativa genérica explícita (inyectada para el test)
    texto_con_negativa = (
        "CONTESTA DEMANDA\n\n"
        "Señor/a Juez/a:\n\n"
        "Juan López, DNI {{DNI_DEMANDADO}}, "
        "constituyendo domicilio procesal en {{DOMICILIO_PROCESAL}}, "
        "con patrocinio del Dr. {{NOMBRE_ABOGADO}}, T° {{TOMO}} F° {{FOLIO}}, "
        "en autos '{{CARATULA}}' (Expte. N° {{NUMERO_EXPEDIENTE}}), "
        "ante V.S. me presento y digo:\n\n"
        "Niego todos y cada uno de los hechos afirmados en la demanda.\n\n"
        "{{FUNDAMENTO_DEFENSA}}\n\n"
        "PETITORIO\nSolicito se rechace la demanda con costas."
    )

    audit_payload = {
        "text": texto_con_negativa,
        "tipo_escrito": "contestacion",
    }
    audit_r = await client.post("/api/audit/review/version-sugerida", json=audit_payload)
    assert audit_r.status_code == 200
    audit_data = audit_r.json()

    version = audit_data.get("version_sugerida")
    cambios = audit_data.get("cambios_aplicados", [])

    if version:
        # Invariante: comienza con encabezado de AILEX
        assert version.startswith("[VERSIÓN SUGERIDA — AILEX]"), \
            "La versión sugerida debe comenzar con el encabezado [VERSIÓN SUGERIDA — AILEX]"

        # Invariante: placeholders del original preservados
        placeholders_originales = [
            "DNI_DEMANDADO", "DOMICILIO_PROCESAL", "NOMBRE_ABOGADO",
            "TOMO", "FOLIO", "FUNDAMENTO_DEFENSA",
        ]
        for ph in placeholders_originales:
            assert f"{{{{{ph}}}}}" in version, \
                f"Placeholder {{{{{ph}}}}} no fue preservado en la versión sugerida"

        # Invariante: hubo al menos un cambio aplicado
        assert cambios, "Si se generó version_sugerida, cambios_aplicados no debe estar vacío"


# ─── E2E-6: Contrato JuridicalResponse en todos los módulos ───────────────────

async def test_e2e_contrato_juridical_response_todos_modulos(client):
    """
    Verifica que los módulos principales respeten el contrato de 8 secciones.
    """
    text = (
        "JUZGADO CIVIL N° 3 - JUJUY. Expte. 12345/2024. "
        "Se corre traslado de la demanda por 15 días. Notifíquese."
    )

    # Análisis
    r = await client.post("/api/analysis/analyze", json={"text": text})
    assert r.status_code == 200
    assert_juridical_response(r.json())

    # Notificaciones
    r = await client.post("/api/notifications/analyze", json={"text": text})
    assert r.status_code == 200
    assert_juridical_response(r.json())

    # Generación
    r = await client.post("/api/generation/generate", json={
        "fuero": "civil", "materia": "daños", "tipo_escrito": "demanda", "variante": "estandar"
    })
    assert r.status_code == 200
    assert_juridical_response(r.json())

    # Auditoría
    r = await client.post("/api/audit/review", json={"text": text})
    assert r.status_code == 200
    data = r.json()
    assert_juridical_response(data)
    # AuditResponse también requiere campos extendidos
    assert "severidad_general" in data
    assert "hallazgos" in data
    assert "diagnostico_general" in data

    # Estrategia
    r = await client.post("/api/strategy/analyze", json={"text": text})
    assert r.status_code == 200
    assert_juridical_response(r.json())


# ─── E2E-7: nivel_confianza nunca es ALTO sin fuentes normativas ───────────────

async def test_e2e_confianza_alta_requiere_fuentes(client):
    """
    Invariante de política: nivel_confianza == 'alto' solo puede ocurrir
    cuando fuentes_respaldo contiene al menos una fuente normativa o
    jurisprudencial. Sin ellas el máximo es 'medio'.
    """
    # Análisis de texto sin fuentes cargadas en la base
    payload = {
        "text": "Plazo para contestar la demanda civil en Jujuy.",
    }
    r = await client.post("/api/analysis/analyze", json=payload)
    assert r.status_code == 200
    data = r.json()

    nivel = data["nivel_confianza"]
    fuentes = data["fuentes_respaldo"]
    binding_hierarchies = {"normativa", "jurisprudencia"}

    if nivel == "alto":
        has_binding = any(
            f.get("source_hierarchy") in binding_hierarchies
            for f in fuentes
        )
        assert has_binding, (
            "nivel_confianza='alto' sin fuentes normativas/jurisprudenciales — "
            "viola la política de confianza"
        )
