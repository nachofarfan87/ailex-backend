"""
AILEX — Generador de versión sugerida y clasificador de severidad.

Dos responsabilidades:
1. classify_severidad_general(): determinar la severidad global del escrito.
2. VersionSugeridaBuilder: generar versión mejorada del escrito aplicando
   correcciones prudentes sin inventar hechos ni normativa.

REGLAS:
  - No inventar hechos ni normativa.
  - No cambiar el contenido sustancial.
  - Usar {{PLACEHOLDER}} para datos que faltan.
  - Documentar cada cambio aplicado.
  - La versión sugerida siempre comienza con [VERSIÓN SUGERIDA — AILEX].
  - Solo aplicar correcciones que mejoran la estructura o la claridad.
"""

import re
from app.modules.audit.schemas import (
    Hallazgo, TipoHallazgo, Severidad, SeveridadGeneral, CaracterHallazgo,
)
from app.modules.audit import heuristics as H


# ─── Clasificador de severidad global ─────────────────────────────────────────

def classify_severidad_general(hallazgos: list[Hallazgo]) -> SeveridadGeneral:
    """
    Determinar la severidad global del escrito según los hallazgos.

    Lógica:
      - Al menos un hallazgo GRAVE → SeveridadGeneral.GRAVE
      - Al menos un hallazgo MODERADO (ninguno grave) → SeveridadGeneral.MODERADA
      - Solo hallazgos LEVES → SeveridadGeneral.LEVE
      - Sin hallazgos → SeveridadGeneral.SIN_PROBLEMAS
    """
    if not hallazgos:
        return SeveridadGeneral.SIN_PROBLEMAS

    sevs = {h.severidad for h in hallazgos}
    if Severidad.GRAVE in sevs:
        return SeveridadGeneral.GRAVE
    if Severidad.MODERADA in sevs:
        return SeveridadGeneral.MODERADA
    return SeveridadGeneral.LEVE


def build_diagnostico(
    hallazgos: list[Hallazgo],
    severidad: SeveridadGeneral,
    tipo_escrito: str = None,
    fuentes_count: int = 0,
) -> str:
    """
    Generar diagnóstico general textual del escrito.
    """
    tipo_str = f" ({tipo_escrito})" if tipo_escrito else ""
    respaldo_str = (
        f", con {fuentes_count} fuente(s) de respaldo documental"
        if fuentes_count > 0
        else ", sin respaldo documental recuperado"
    )
    graves = [h for h in hallazgos if h.severidad == Severidad.GRAVE]
    moderadas = [h for h in hallazgos if h.severidad == Severidad.MODERADA]
    leves = [h for h in hallazgos if h.severidad == Severidad.LEVE]

    if severidad == SeveridadGeneral.SIN_PROBLEMAS:
        return (
            f"Escrito{tipo_str} sin problemas formales detectados{respaldo_str}. "
            "Se recomienda revisión manual del contenido sustancial "
            "y verificación de normativa antes de presentar."
        )
    elif severidad == SeveridadGeneral.LEVE:
        return (
            f"Escrito{tipo_str} con {len(leves)} observación(es) menor(es){respaldo_str}. "
            "El escrito puede presentarse con ajustes menores de redacción."
        )
    elif severidad == SeveridadGeneral.MODERADA:
        return (
            f"Escrito{tipo_str} con {len(moderadas)} debilidad(es) moderada(s)"
            + (f" y {len(leves)} leve(s)" if leves else "")
            + f"{respaldo_str}. "
            "Se recomienda corregir antes de presentar."
        )
    else:  # GRAVE
        return (
            f"Escrito{tipo_str} con {len(graves)} problema(s) grave(s)"
            + (f" y {len(moderadas)} moderado(s)" if moderadas else "")
            + f"{respaldo_str}. "
            "No presentar sin corregir los problemas graves detectados."
        )


def build_debilidades(hallazgos: list[Hallazgo]) -> list[str]:
    """
    Construir lista de debilidades desde hallazgos (sin duplicar con los hallazgos).
    Resume por categoría y severidad.
    """
    debilidades: list[str] = []
    por_tipo: dict[TipoHallazgo, list[Hallazgo]] = {}
    for h in hallazgos:
        por_tipo.setdefault(h.tipo, []).append(h)

    if TipoHallazgo.ESTRUCTURA in por_tipo:
        items = por_tipo[TipoHallazgo.ESTRUCTURA]
        secciones = [h.seccion for h in items if h.seccion]
        debilidades.append(
            f"Estructura: {len(items)} problema(s) detectado(s)"
            + (f" en {', '.join(set(secciones))}" if secciones else "") + "."
        )

    if TipoHallazgo.REDACCION in por_tipo:
        items = por_tipo[TipoHallazgo.REDACCION]
        debilidades.append(
            f"Redacción: {len(items)} problema(s) — "
            + "; ".join(h.observacion[:60] + "..." for h in items[:2])
        )

    if TipoHallazgo.ARGUMENTAL in por_tipo:
        items = por_tipo[TipoHallazgo.ARGUMENTAL]
        graves_arg = [h for h in items if h.severidad == Severidad.GRAVE]
        debilidades.append(
            f"Argumental: {len(items)} debilidad(es)"
            + (f", incluyendo {len(graves_arg)} grave(s)" if graves_arg else "") + "."
        )

    if TipoHallazgo.RIESGO_PROCESAL in por_tipo:
        items = por_tipo[TipoHallazgo.RIESGO_PROCESAL]
        debilidades.append(
            f"Riesgo procesal: {len(items)} riesgo(s) identificado(s)."
        )

    if TipoHallazgo.GUARDRAIL in por_tipo:
        items = por_tipo[TipoHallazgo.GUARDRAIL]
        debilidades.append(
            f"Contenido problemático: {len(items)} violación(es) de políticas del sistema."
        )

    return debilidades


def build_mejoras_sugeridas(hallazgos: list[Hallazgo]) -> list[str]:
    """
    Consolidar mejoras únicas desde los hallazgos (sin duplicar).
    """
    mejoras: list[str] = []
    seen: set[str] = set()
    for h in sorted(hallazgos, key=lambda x: (
        0 if x.severidad == Severidad.GRAVE
        else 1 if x.severidad == Severidad.MODERADA
        else 2
    )):
        if h.mejora_sugerida and h.mejora_sugerida not in seen:
            mejoras.append(h.mejora_sugerida)
            seen.add(h.mejora_sugerida)
    return mejoras


# ─── Generador de versión sugerida ────────────────────────────────────────────

class VersionSugeridaBuilder:
    """
    Genera una versión mejorada del escrito aplicando correcciones prudentes.

    INVARIANTES:
    - No inventa hechos.
    - No inventa normativa ni artículos.
    - No cambia el relato de los hechos.
    - Mantiene todos los {{PLACEHOLDER}} presentes.
    - Solo agrega secciones faltantes con {{PLACEHOLDER}} explícito.
    - Documenta cada cambio en cambios_aplicados.
    """

    ENCABEZADO_NOTA = (
        "[VERSIÓN SUGERIDA — AILEX]\n"
        "[ADVERTENCIA: borrador mejorado con correcciones estructurales y de redacción.]\n"
        "[Revisar todos los cambios antes de presentar. No reemplaza criterio del abogado.]\n\n"
    )

    def __init__(
        self,
        text: str,
        hallazgos: list[Hallazgo],
        tipo_escrito: str = None,
    ):
        self.original = text
        self.hallazgos = hallazgos
        self.tipo_escrito = tipo_escrito
        self.cambios: list[str] = []

    def build(self) -> tuple[str, list[str]]:
        """
        Generar la versión sugerida.
        Retorna (version_sugerida, cambios_aplicados).
        """
        result = self.original

        # Solo generar si hay hallazgos moderados o graves
        hallazgos_relevantes = [
            h for h in self.hallazgos
            if h.severidad in (Severidad.GRAVE, Severidad.MODERADA)
        ]
        if not hallazgos_relevantes:
            return result, []

        # Aplicar correcciones en orden de importancia
        result = self._fix_negativa_generica(result)
        result = self._fix_peticion_ambigua(result)
        result = self._fix_certeza_artificial(result)
        result = self._add_missing_encabezado(result)
        result = self._add_missing_petitorio(result)
        result = self._add_missing_domicilio(result)
        result = self._add_missing_prueba(result)

        if self.cambios:
            result = self.ENCABEZADO_NOTA + result
        else:
            return self.original, []

        return result, self.cambios

    # ── Correcciones de redacción ─────────────────────────────────────────────

    def _fix_negativa_generica(self, text: str) -> str:
        """Reemplazar negativa genérica con estructura de negativa específica."""
        m = H.RE_NEGATIVA_GENERICA.search(text)
        if not m:
            return text

        reemplazo = (
            "En relación con los hechos invocados en la demanda, formulo negativa "
            "específica en los siguientes términos:\n"
            "a) {{HECHO_1_IDENTIFICAR}}: [niego / reconozco / desconozco]\n"
            "b) {{HECHO_2_IDENTIFICAR}}: [niego / reconozco / desconozco]\n"
            "[Continuar con negativa específica por cada hecho de la demanda]\n"
            "[ADVERTENCIA: eliminar ítems genéricos y completar hecho por hecho]"
        )

        # Reemplazar solo la primera ocurrencia
        result = text[:m.start()] + reemplazo + text[m.end():]
        self.cambios.append(
            "Negativa genérica reemplazada por estructura de negativa específica "
            "con {{PLACEHOLDER}} para completar hecho por hecho."
        )
        return result

    def _fix_peticion_ambigua(self, text: str) -> str:
        """Marcar petición ambigua con indicación de revisión."""
        m = H.RE_PETICION_AMBIGUA.search(text)
        if not m:
            return text

        marcado = f"[REVISAR — PETICIÓN AMBIGUA: '{m.group(0)}' — precisar qué se solicita concretamente]"
        result = text[:m.start()] + marcado + text[m.end():]
        self.cambios.append(
            f"Petición ambigua marcada para revisión: '{m.group(0)[:50]}...'"
        )
        return result

    def _fix_certeza_artificial(self, text: str) -> str:
        """Reemplazar expresiones de certeza artificial por lenguaje cautelar."""
        _REEMPLAZOS = {
            r"indubitablemente\b": "conforme surge de las constancias",
            r"sin\s+lugar\s+a\s+dudas?\b": "prima facie",
            r"es\s+evidente\s+que\b": "se desprende que",
            r"indiscutiblemente\b": "conforme las constancias del caso",
            r"es\s+indiscutible\b": "surge de las constancias",
            r"no\s+cabe\s+duda\b": "cabe concluir provisoriamente",
            r"categóricamente\s+cierto\b": "acreditado en autos",
        }
        result = text
        for patron, reemplazo in _REEMPLAZOS.items():
            nuevo = re.sub(patron, reemplazo, result, flags=re.IGNORECASE, count=1)
            if nuevo != result:
                self.cambios.append(
                    f"Expresión de certeza artificial corregida por lenguaje cautelar."
                )
                result = nuevo
                break  # Una corrección por vez para no alterar demasiado
        return result

    # ── Adición de secciones faltantes ────────────────────────────────────────

    def _add_missing_encabezado(self, text: str) -> str:
        """Agregar encabezado si falta."""
        if H.RE_ENCABEZADO.search(text):
            return text
        # Solo agregar si hay hallazgo de encabezado faltante
        if not any(h.seccion == "encabezado" and h.tipo == TipoHallazgo.ESTRUCTURA
                   for h in self.hallazgos):
            return text

        stub = "Señor/a Juez/a:\n\n"
        self.cambios.append("Encabezado 'Señor/a Juez/a' agregado al inicio.")
        return stub + text

    def _add_missing_petitorio(self, text: str) -> str:
        """Agregar sección de petitorio si falta."""
        if H.RE_PETITORIO.search(text):
            return text
        if not any(h.seccion == "petitorio" and h.tipo == TipoHallazgo.ESTRUCTURA
                   for h in self.hallazgos):
            return text

        stub = (
            "\n\nPETITORIO\n"
            "Por todo lo expuesto, solicito a V.S.:\n"
            "1. {{PETICION_PRINCIPAL}}\n"
            "2. {{PETICION_ACCESORIA_SI_CORRESPONDE}}\n"
            "[ADVERTENCIA: completar el petitorio con las pretensiones concretas del caso]\n"
            "\nProveer de conformidad, SERÁ JUSTICIA."
        )
        self.cambios.append(
            "Sección PETITORIO agregada con {{PLACEHOLDER}} (faltaba en el texto original)."
        )
        return text + stub

    def _add_missing_domicilio(self, text: str) -> str:
        """Sugerir constitución de domicilio si falta."""
        if H.RE_DOMICILIO.search(text):
            return text
        if not any(h.seccion == "domicilio" for h in self.hallazgos):
            return text

        # Insertar como nota al inicio del escrito (después del encabezado si existe)
        nota = (
            "[AGREGAR: constituyendo domicilio procesal en {{DOMICILIO_PROCESAL}} "
            "y domicilio electrónico en {{DOMICILIO_ELECTRONICO}}]\n"
        )
        # Intentar insertar después del encabezado
        m = H.RE_ENCABEZADO.search(text)
        if m:
            pos = text.find("\n", m.end())
            if pos >= 0:
                result = text[:pos + 1] + nota + text[pos + 1:]
                self.cambios.append(
                    "Nota de domicilio procesal agregada (faltaba en el texto original)."
                )
                return result

        self.cambios.append(
            "Nota de domicilio procesal agregada al inicio."
        )
        return nota + text

    def _add_missing_prueba(self, text: str) -> str:
        """Agregar sección de prueba si falta y corresponde al tipo de escrito."""
        tipo_norm = (self.tipo_escrito or "").lower()
        tipos_con_prueba = {"demanda", "contestacion", ""}
        if tipo_norm not in tipos_con_prueba:
            return text
        if H.RE_PRUEBA_SECCION.search(text):
            return text
        if not any(h.seccion == "prueba" and h.tipo == TipoHallazgo.ESTRUCTURA
                   for h in self.hallazgos):
            return text

        # Agregar antes del petitorio si existe, si no al final
        stub = (
            "\nPRUEBA\n"
            "Ofrezco los siguientes medios de prueba:\n"
            "{{OFRECIMIENTO_DE_PRUEBA}}\n"
            "[ADVERTENCIA: detallar cada medio: documental, testimonial, pericial, etc.]\n"
        )
        m = H.RE_PETITORIO.search(text)
        if m:
            # Insertar antes del petitorio
            pos = m.start()
            result = text[:pos] + stub + "\n" + text[pos:]
            self.cambios.append(
                "Sección PRUEBA agregada antes del petitorio con {{PLACEHOLDER}}."
            )
            return result

        self.cambios.append(
            "Sección PRUEBA agregada con {{PLACEHOLDER}} (faltaba en el texto original)."
        )
        return text + stub
