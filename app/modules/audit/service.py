"""
AILEX — Módulo de Auditoría y Revisión de Escritos Forenses.

Pipeline de revisión:
  1. Normalización de entrada
  2. Chequeos estructurales, de redacción, argumentales y procesales
  3. Detección de guardrails
  4. Detección de fortalezas
  5. Clasificación de severidad global
  6. Generación de versión sugerida (opcional)
  7. Recuperación de fuentes de respaldo (RAG)
  8. Construcción de AuditResponse vía ReasoningPipeline

REGLAS:
  - No afirmar error jurídico definitivo si depende de norma no verificada.
  - Distinguir siempre: extraído / inferido / sugerencia.
  - No inventar normativa para corregir citas sospechosas.
  - No reescribir hechos.
  - La versión sugerida mantiene {{PLACEHOLDER}} para datos faltantes.
"""

from app.policies.reasoning_policy import ReasoningPipeline
from app.policies.validators import ValidationResult
from app.modules.normalization.service import NormalizationService
from app.modules.search.retrieval import retrieve_sources
from app.modules.audit.schemas import (
    AuditResponse, Hallazgo, Severidad, SeveridadGeneral,
    TipoHallazgo, CaracterHallazgo,
)
from app.modules.audit import checks, suggestions as sug


class AuditService:
    """
    Servicio de auditoría y revisión de escritos forenses.

    Detecta problemas concretos con clasificación explícita:
    extraído | inferido | sugerencia.

    Retorna AuditResponse (superset de JuridicalResponse).
    """

    def __init__(self):
        self._normalizer = NormalizationService()

    async def review(
        self,
        text: str,
        tipo_escrito: str = None,
        demanda_original: str = None,
        session_id: str = None,
        incluir_version_sugerida: bool = True,
    ) -> tuple[AuditResponse, ValidationResult]:
        """
        Revisar un escrito jurídico.

        Retorna (AuditResponse, ValidationResult).

        AuditResponse incluye:
          - diagnostico_general: diagnóstico textual global
          - severidad_general: "grave" | "moderada" | "leve" | "sin_problemas"
          - hallazgos: lista estructurada de hallazgos individuales
          - fortalezas: aspectos positivos detectados
          - debilidades: resumen de debilidades por categoría
          - mejoras_sugeridas: lista de acciones concretas
          - version_sugerida: borrador mejorado (si aplica)
          - cambios_aplicados: cambios realizados en la versión sugerida
          - datos_faltantes: según contrato base
          - nivel_confianza: refleja disponibilidad de fuentes RAG
        """
        if not text or not text.strip():
            error_response = ReasoningPipeline.make_response_with_error(
                modulo="auditoria",
                error_description="Texto del escrito vacío. No hay contenido para revisar.",
            )
            vr = ValidationResult()
            vr.add_error("Texto vacío — no se puede revisar.")
            audit_error = AuditResponse(
                **error_response.model_dump(),
                diagnostico_general="Sin texto para revisar.",
                severidad_general=SeveridadGeneral.SIN_PROBLEMAS,
            )
            return audit_error, vr

        # ── 1. Normalización ──────────────────────────────────────────────────
        normalized = await self._normalizer.normalize(text)
        entities = normalized.get("entities", {})
        text_clean = normalized.get("text_clean", text)
        tipo_detectado = normalized.get("doc_type", "desconocido")
        tipo_efectivo = tipo_escrito or (
            tipo_detectado if tipo_detectado != "desconocido" else None
        )

        pipeline = ReasoningPipeline(modulo="auditoria", session_id=session_id)

        # ── 2. Ejecutar todos los chequeos ────────────────────────────────────
        todos_los_hallazgos: list[Hallazgo] = []
        todos_los_hallazgos.extend(checks.check_estructura(text_clean, tipo_efectivo))
        todos_los_hallazgos.extend(checks.check_redaccion(text_clean))
        todos_los_hallazgos.extend(checks.check_argumental(text_clean, entities))
        todos_los_hallazgos.extend(checks.check_riesgo_procesal(text_clean, tipo_efectivo))
        todos_los_hallazgos.extend(checks.check_guardrails(text_clean))

        # ── 3. Fortalezas ─────────────────────────────────────────────────────
        fortalezas = checks.detect_fortalezas(text_clean, entities)

        # ── 4. Clasificar severidad ───────────────────────────────────────────
        severidad = sug.classify_severidad_general(todos_los_hallazgos)

        # ── 5. Versión sugerida ───────────────────────────────────────────────
        version_sugerida = None
        cambios_aplicados: list[str] = []
        if incluir_version_sugerida and todos_los_hallazgos:
            builder = sug.VersionSugeridaBuilder(
                text=text,
                hallazgos=todos_los_hallazgos,
                tipo_escrito=tipo_efectivo,
            )
            version_sugerida, cambios_aplicados = builder.build()
            if not cambios_aplicados:
                version_sugerida = None

        # ── 6. RAG: fuentes de respaldo ───────────────────────────────────────
        audit_query_parts = []
        if tipo_efectivo:
            audit_query_parts.append(tipo_efectivo)
        arts = entities.get("articulo", [])
        for art in arts[:3]:
            if isinstance(art, str):
                audit_query_parts.append(f"artículo {art}")
        if not audit_query_parts:
            audit_query_parts.append(text_clean[:200])

        fuentes = await retrieve_sources(
            query=" ".join(audit_query_parts),
            module="audit",
            jurisdiction="Jujuy",
            top_k=5,
        )

        # ── 7. Construir componentes del pipeline ─────────────────────────────

        # Hechos relevantes (extraídos e inferidos desde hallazgos graves/moderados)
        hechos_relevantes = []
        for h in todos_los_hallazgos:
            if h.severidad in (Severidad.GRAVE, Severidad.MODERADA):
                if h.caracter == CaracterHallazgo.EXTRAIDO:
                    hecho = pipeline.tag_extracted(
                        h.texto_detectado
                        if h.texto_detectado
                        else h.observacion[:120]
                    )
                else:
                    hecho = pipeline.tag_inference(h.observacion[:120])
                hechos_relevantes.append(hecho)

        if fortalezas:
            hechos_relevantes.append(
                pipeline.tag_extracted(
                    f"Fortalezas detectadas: {len(fortalezas)} aspectos positivos."
                )
            )

        # Encuadre preliminar
        encuadre = []
        if tipo_efectivo:
            encuadre.append(f"Tipo de escrito: {tipo_efectivo}.")
        if tipo_detectado and tipo_detectado != "desconocido" and not tipo_escrito:
            encuadre.append(f"Tipo detectado automáticamente: {tipo_detectado}.")
        graves = [h for h in todos_los_hallazgos if h.severidad == Severidad.GRAVE]
        moderadas = [h for h in todos_los_hallazgos if h.severidad == Severidad.MODERADA]
        leves = [h for h in todos_los_hallazgos if h.severidad == Severidad.LEVE]
        encuadre.append(
            f"Hallazgos: {len(graves)} grave(s), {len(moderadas)} moderado(s), "
            f"{len(leves)} leve(s)."
        )
        encuadre.append(f"Severidad global: {severidad.value}.")
        if fuentes:
            encuadre.append(f"Respaldo documental recuperado: {len(fuentes)} fuente(s).")
        else:
            encuadre.append(
                "Sin fuentes de respaldo recuperadas. "
                "Las observaciones se basan en heurísticas — verificar normativamente."
            )

        # Acciones sugeridas desde hallazgos (priorizadas)
        acciones = []
        hallazgos_con_mejora = sorted(
            [h for h in todos_los_hallazgos if h.mejora_sugerida],
            key=lambda x: (
                0 if x.severidad == Severidad.GRAVE
                else 1 if x.severidad == Severidad.MODERADA
                else 2
            )
        )
        for h in hallazgos_con_mejora[:8]:  # límite razonable
            prioridad = "alta" if h.severidad == Severidad.GRAVE else (
                "media" if h.severidad == Severidad.MODERADA else "baja"
            )
            acciones.append(pipeline.suggest(
                h.mejora_sugerida,
                priority=prioridad,
                risk=(
                    "Problema grave — no presentar sin corregir"
                    if h.severidad == Severidad.GRAVE else None
                ),
            ))

        # Riesgos observados
        riesgos_obs = []
        arts_sospechosos = [
            h for h in todos_los_hallazgos
            if h.tipo == TipoHallazgo.ARGUMENTAL and "Art." in (h.texto_detectado or "")
        ]
        if arts_sospechosos:
            riesgos_obs.append(
                f"{len(arts_sospechosos)} cita(s) normativa(s) sospechosa(s). "
                "Una cita incorrecta debilita el escrito y puede generar observaciones del tribunal."
            )
        for h in todos_los_hallazgos:
            if h.severidad == Severidad.GRAVE and h.tipo == TipoHallazgo.RIESGO_PROCESAL:
                riesgos_obs.append(h.observacion)
        if not fuentes:
            riesgos_obs.append(
                "Sin respaldo documental — los hallazgos se basan en heurísticas. "
                "Verificar cada observación contra la normativa aplicable."
            )

        # Datos faltantes
        datos_faltantes_list = []
        if not demanda_original and tipo_efectivo in ("contestacion", None):
            datos_faltantes_list.append(pipeline.missing(
                description="Demanda original para contrastar hechos y pretensiones",
                impact="Sin ella no se puede verificar si la contestación cubre todos los hechos",
                required_for="Revisión integral de contestación de demanda",
            ))

        # Debilidades y mejoras sugeridas
        debilidades = sug.build_debilidades(todos_los_hallazgos)
        mejoras_sugeridas_list = sug.build_mejoras_sugeridas(todos_los_hallazgos)

        # Diagnóstico general
        diagnostico = sug.build_diagnostico(
            todos_los_hallazgos, severidad, tipo_efectivo, len(fuentes)
        )

        # Resumen ejecutivo
        fuentes_str = f", {len(fuentes)} fuente(s) de respaldo" if fuentes else ""
        n_graves = len(graves)
        n_total = len(todos_los_hallazgos)
        if n_total == 0:
            resumen = (
                f"Sin problemas formales detectados{fuentes_str}. "
                "Revisión manual recomendada para el contenido sustancial."
            )
        elif n_graves > 0:
            resumen = (
                f"Se detectaron {n_total} hallazgo(s) ({n_graves} grave(s)){fuentes_str}. "
                "No presentar sin corregir los problemas graves. "
                "Ver hallazgos y versión sugerida."
            )
        else:
            resumen = (
                f"Se detectaron {n_total} hallazgo(s){fuentes_str}. "
                "Correcciones recomendadas antes de presentar. "
                "Ver hallazgos y mejoras sugeridas."
            )

        # ── 8. Ejecutar pipeline base ─────────────────────────────────────────
        base_response, vr = pipeline.run(
            resumen_ejecutivo=resumen,
            hechos_relevantes=hechos_relevantes,
            encuadre_preliminar=encuadre,
            acciones_sugeridas=acciones,
            riesgos_observaciones=riesgos_obs,
            fuentes_respaldo=fuentes,
            datos_faltantes=datos_faltantes_list,
        )

        # ── 9. Construir AuditResponse ────────────────────────────────────────
        audit_response = AuditResponse(
            **base_response.model_dump(),
            diagnostico_general=diagnostico,
            severidad_general=severidad,
            hallazgos=todos_los_hallazgos,
            fortalezas=fortalezas,
            debilidades=debilidades,
            mejoras_sugeridas=mejoras_sugeridas_list,
            version_sugerida=version_sugerida,
            cambios_aplicados=cambios_aplicados,
            tipo_escrito_detectado=tipo_detectado if tipo_detectado != "desconocido" else None,
        )

        return audit_response, vr

    async def get_severidad(
        self, text: str, tipo_escrito: str = None
    ) -> dict:
        """
        Evaluación rápida de severidad sin versión sugerida ni RAG.
        Para uso en endpoint /review/severidad.
        """
        if not text or not text.strip():
            return {
                "severidad_general": SeveridadGeneral.SIN_PROBLEMAS.value,
                "total_hallazgos": 0,
                "por_categoria": {},
                "graves": 0, "moderados": 0, "leves": 0,
            }

        normalized = await self._normalizer.normalize(text)
        text_clean = normalized.get("text_clean", text)
        entities = normalized.get("entities", {})
        tipo_detectado = normalized.get("doc_type", None)
        tipo_efectivo = tipo_escrito or (
            tipo_detectado if tipo_detectado != "desconocido" else None
        )

        todos = []
        todos.extend(checks.check_estructura(text_clean, tipo_efectivo))
        todos.extend(checks.check_redaccion(text_clean))
        todos.extend(checks.check_argumental(text_clean, entities))
        todos.extend(checks.check_riesgo_procesal(text_clean, tipo_efectivo))

        severidad = sug.classify_severidad_general(todos)

        por_categoria: dict[str, int] = {}
        for h in todos:
            cat = h.tipo.value
            por_categoria[cat] = por_categoria.get(cat, 0) + 1

        return {
            "severidad_general": severidad.value,
            "total_hallazgos": len(todos),
            "por_categoria": por_categoria,
            "graves": len([h for h in todos if h.severidad == Severidad.GRAVE]),
            "moderados": len([h for h in todos if h.severidad == Severidad.MODERADA]),
            "leves": len([h for h in todos if h.severidad == Severidad.LEVE]),
        }
