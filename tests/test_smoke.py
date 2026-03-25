"""
AILEX — Smoke tests de endpoints.

Verifica que todos los endpoints responden correctamente con inputs mínimos.
No ejercita la lógica de negocio — solo garantiza que el pipeline no falla
ni devuelve errores 500 ante requests bien formados.

Uso:
  cd backend
  pytest tests/test_smoke.py -v

Requiere:
  pip install httpx pytest pytest-asyncio
"""

# ─── Sistema ──────────────────────────────────────────────────────────────────

async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data


# ─── Notificaciones ───────────────────────────────────────────────────────────

async def test_notifications_analyze(client):
    payload = {
        "text": (
            "JUZGADO CIVIL N° 3 - JUJUY\n"
            "Expte. N° 12345/2024\n"
            "Córrase traslado de la demanda por 15 días. Notifíquese."
        )
    }
    r = await client.post("/api/notifications/analyze", json=payload)
    assert r.status_code == 200
    data = r.json()
    # Estructura JuridicalResponse
    assert "resumen_ejecutivo" in data
    assert "nivel_confianza" in data
    assert "modulo_origen" in data


async def test_notifications_analyze_empty_text(client):
    r = await client.post("/api/notifications/analyze", json={"text": ""})
    # Texto vacío → respuesta válida (no 500)
    assert r.status_code in (200, 422)


# ─── Análisis ─────────────────────────────────────────────────────────────────

async def test_analysis_analyze(client):
    payload = {
        "text": (
            "Se corre traslado de la demanda al demandado por el plazo "
            "de quince (15) días hábiles. Notifíquese."
        )
    }
    r = await client.post("/api/analysis/analyze", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "resumen_ejecutivo" in data
    assert "nivel_confianza" in data


# ─── Generación ───────────────────────────────────────────────────────────────

async def test_generation_generate_demanda(client):
    payload = {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "demanda",
        "variante": "estandar",
    }
    r = await client.post("/api/generation/generate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "borrador" in data
    assert "{{" in data["borrador"], "El borrador debe contener placeholders sin completar"
    assert "placeholders_detectados" in data
    assert len(data["placeholders_detectados"]) > 0
    assert data["variante_aplicada"] == "estandar"
    assert data["modulo_origen"] == "generacion"


async def test_generation_generate_variante_alias(client):
    """El alias 'conservadora' debe normalizarse a 'conservador'."""
    payload = {
        "fuero": "civil",
        "materia": "daños",
        "tipo_escrito": "demanda",
        "variante": "conservadora",
    }
    r = await client.post("/api/generation/generate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["variante_aplicada"] == "conservador"


async def test_generation_generate_tipo_invalido(client):
    payload = {
        "fuero": "civil",
        "materia": "general",
        "tipo_escrito": "tipo_inexistente",
        "variante": "estandar",
    }
    r = await client.post("/api/generation/generate", json=payload)
    # Debe responder (no 500) — 200 con advertencia o 422
    assert r.status_code in (200, 422)


async def test_generation_templates(client):
    r = await client.get("/api/generation/templates")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "templates" in data
    assert data["total"] > 0


async def test_generation_template_por_tipo(client):
    r = await client.get("/api/generation/templates/demanda")
    assert r.status_code == 200
    data = r.json()
    assert data["tipo_escrito"] == "demanda"
    assert "placeholders_requeridos" in data
    assert "checklist_previo" in data


async def test_generation_template_placeholders(client):
    r = await client.get("/api/generation/templates/demanda/placeholders")
    assert r.status_code == 200
    data = r.json()
    assert "placeholders_requeridos" in data
    assert len(data["placeholders_requeridos"]) > 0


async def test_generation_variantes(client):
    r = await client.get("/api/generation/variantes")
    assert r.status_code == 200
    data = r.json()
    assert "variantes" in data
    nombres = [v["nombre"] for v in data["variantes"]]
    assert "conservador" in nombres
    assert "estandar" in nombres
    assert "firme" in nombres
    assert "agresivo_prudente" in nombres


async def test_generation_draft(client):
    r = await client.get("/api/generation/templates/contesta_traslado/draft?variante=estandar")
    assert r.status_code == 200
    data = r.json()
    assert "borrador" in data
    assert "{{" in data["borrador"]


# ─── Auditoría ────────────────────────────────────────────────────────────────

async def test_audit_review_negativa_generica(client):
    payload = {
        "text": (
            "CONTESTA DEMANDA\n\n"
            "Señor/a Juez/a:\n\n"
            "Juan López, DNI 25.678.901, constituyendo domicilio procesal en "
            "Belgrano 456, San Salvador de Jujuy, con patrocinio del Dr. Ruiz T° XII F° 180, "
            "en autos 'González c/ López' (Expte. 345/2025), ante V.S. digo:\n\n"
            "Niego todos y cada uno de los hechos afirmados en la demanda.\n\n"
            "Solicito se rechace la demanda con costas."
        ),
        "tipo_escrito": "contestacion",
    }
    r = await client.post("/api/audit/review", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "severidad_general" in data
    assert "hallazgos" in data
    assert "diagnostico_general" in data
    assert "fortalezas" in data
    # Debe detectar negativa genérica
    assert data["severidad_general"] in ("grave", "moderada", "leve", "sin_problemas")
    tipos = [h["tipo"] for h in data["hallazgos"]]
    assert "redaccion" in tipos


async def test_audit_review_empty_text(client):
    r = await client.post("/api/audit/review", json={"text": ""})
    assert r.status_code in (200, 422)


async def test_audit_hallazgos(client):
    payload = {
        "text": (
            "Señor/a Juez/a:\n"
            "Niego todos y cada uno de los hechos. Solicito lo que VS estime pertinente."
        )
    }
    r = await client.post("/api/audit/review/hallazgos", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "hallazgos" in data
    assert "severidad_general" in data
    assert "total_hallazgos" in data


async def test_audit_version_sugerida(client):
    payload = {
        "text": (
            "Señor/a Juez/a:\n\n"
            "Niego todos y cada uno de los hechos afirmados en la demanda.\n\n"
            "PETITORIO\nSolicito se rechace la demanda."
        ),
        "tipo_escrito": "contestacion",
    }
    r = await client.post("/api/audit/review/version-sugerida", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "version_sugerida" in data
    assert "cambios_aplicados" in data


async def test_audit_severidad(client):
    payload = {
        "text": "Señor/a Juez/a:\nSolicito se tenga presente. Proveer de conformidad."
    }
    r = await client.post("/api/audit/review/severidad", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "severidad_general" in data
    assert "total_hallazgos" in data
    assert "por_categoria" in data
    assert data["severidad_general"] in ("grave", "moderada", "leve", "sin_problemas")


# ─── Estrategia ───────────────────────────────────────────────────────────────

async def test_strategy_analyze(client):
    payload = {
        "text": (
            "Se corre traslado de la demanda por 5 días. "
            "El cliente aún no completó la documentación."
        ),
        "tipo_proceso": "civil",
        "etapa_procesal": "traslado de demanda",
        "objetivo_abogado": "definir respuesta inicial sin cerrar defensas",
    }
    r = await client.post("/api/strategy/analyze", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "opciones_estrategicas" in data
    assert "recomendacion_prudente" in data
    assert "nivel_confianza" in data


async def test_strategy_options(client):
    payload = {
        "text": "Traslado de demanda. Plazo de 15 días.",
        "tipo_proceso": "civil",
    }
    r = await client.post("/api/strategy/options", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "opciones_estrategicas" in data


async def test_strategy_quick(client):
    payload = {"text": "Se notificó sentencia desfavorable. Evaluar recurso."}
    r = await client.post("/api/strategy/quick", json=payload)
    assert r.status_code == 200


# ─── Workflow ─────────────────────────────────────────────────────────────────

async def test_workflow_notification_response_traslado(client):
    payload = {
        "texto": (
            "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
            "Expte. N° 12345/2024\n"
            "San Salvador de Jujuy, 5 de marzo de 2026.\n"
            "Córrase traslado de la demanda por 5 días. Notifíquese."
        ),
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "objetivo_usuario": "preparar respuesta inicial",
    }
    r = await client.post("/api/workflow/notification-response", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "resumen_caso" in data
    assert "nivel_confianza_global" in data
    assert "tipo_escrito_sugerido" in data
    assert "opciones_estrategicas_resumidas" in data
    assert data["nivel_confianza_global"] in ("alto", "medio", "bajo", "sin_respaldo")


async def test_workflow_sin_generacion(client):
    payload = {
        "texto": "Posible demora en el expediente, sin constancias.",
        "objetivo_usuario": "evaluar situación",
        "generar_borrador": False,
    }
    r = await client.post("/api/workflow/notification-response", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["borrador_inicial"] is None


# ─── Búsqueda ─────────────────────────────────────────────────────────────────

async def test_search_hybrid(client):
    payload = {
        "query": "plazo contestar demanda civil Jujuy",
        "jurisdiction": "Jujuy",
        "top_k": 3,
    }
    r = await client.post("/api/search/hybrid", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert "total" in data


async def test_search_semantic(client):
    payload = {
        "query": "responsabilidad objetiva accidente tránsito",
        "top_k": 3,
    }
    r = await client.post("/api/search/semantic", json=payload)
    assert r.status_code == 200
