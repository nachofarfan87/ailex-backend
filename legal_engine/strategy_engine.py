from __future__ import annotations

import re
import unicodedata
from typing import Any


class StrategyEngine:
    """
    AILEX - Litigation Strategy Engine

    Convierte una consulta en:
    - tipo de accion
    - estrategia juridica
    - parametros clave
    """

    def analyze(self, query: str) -> dict[str, Any]:
        q = self._normalize(query)

        action = self._detect_action(q)
        variables = self._extract_variables(q)
        strategy = self._build_strategy(action, variables)
        strategy = self._validate_strategy(action, variables, strategy)

        return {
            "tipo_accion": action,
            "variables": variables,
            "estrategia": strategy,
        }

    def _normalize(self, text: str) -> str:
        nfkd = unicodedata.normalize("NFKD", (text or "").lower())
        return "".join(char for char in nfkd if not unicodedata.combining(char))

    def _detect_action(self, q: str) -> str:
        if self._is_patrimonial_conflict(q):
            return "conflicto_patrimonial"

        if "ver a mi hijo" in q or "no me deja ver" in q:
            return "regimen_comunicacional"

        if "cuota" in q or "alimento" in q:
            return "alimentos"

        if "divorci" in q or "separar" in q:
            return "divorcio"

        return "desconocido"

    def _extract_variables(self, q: str) -> dict[str, Any]:
        variables: dict[str, Any] = {}

        edades = [int(e) for e in re.findall(r"\b\d{1,2}\b", q)]
        if edades:
            variables["edades_hijos"] = edades
            variables["hay_menor"] = any(e < 18 for e in edades)
            variables["hay_mayor"] = any(e >= 18 for e in edades)
            variables["hay_multiples_edades"] = len(edades) > 1
            variables["categorias_etarias_detectadas"] = self._categorize_age_buckets(edades)
            if len(edades) == 1:
                variables["edad_relevante"] = edades[0]

        estudia = self._contains_any(q, ("estudia", "estudiando", "universidad", "universitario", "facultad", "alumno regular"))
        no_estudia = self._contains_any(q, ("no estudia", "dejo de estudiar", "ya no estudia", "nunca estudio"))
        convive = self._contains_any(q, ("convive", "vive conmigo", "vive con la madre", "vive con su mama", "vive con su padre"))
        trabaja = self._contains_any(q, ("trabaja", "trabajando", "empleo", "empleada", "empleado", "labura"))
        no_trabaja = self._contains_any(q, ("no trabaja", "desocupado", "desocupada", "sin empleo", "no tiene trabajo"))
        ingresos_propios = self._contains_any(q, ("ingresos propios", "tiene ingresos", "cobra sueldo", "mantiene sus gastos"))
        no_ingresos_formales = self._contains_any(q, ("no tiene ingresos formales", "sin ingresos formales", "trabaja en negro"))

        if estudia:
            variables["hijo_estudia"] = True
        if no_estudia:
            variables["hijo_no_estudia"] = True
        if convive:
            variables["convive"] = True
        if trabaja:
            variables["trabaja"] = True
        if no_trabaja:
            variables["no_trabaja"] = True
        if ingresos_propios:
            variables["ingresos_propios"] = True
        if no_ingresos_formales:
            variables["sin_ingresos_formales"] = True

        if "en negro" in q:
            variables["ingresos_negro"] = True
        if "no tiene ingresos" in q or no_trabaja:
            variables["sin_ingresos"] = True
        if no_trabaja and not trabaja:
            variables["sin_autosustento_laboral"] = True

        categoria_hijo = self._categorize_child_support(variables)
        if categoria_hijo:
            variables["categoria_hijo"] = categoria_hijo

        if self._contains_any(q, ("bienes", "casa", "inmueble", "vivienda", "propiedad")):
            variables["hay_bienes"] = True
        if self._contains_any(q, ("cotitularidad", "cotitular", "condominio", "50%", "mitad")):
            variables["cotitularidad"] = True
        if self._contains_any(q, ("ex esposo", "exesposo", "ex esposa", "exesposa", "divorcio", "divorciado", "divorciada")):
            variables["vinculo_ex_conyugal"] = True
        if "hered" in q:
            variables["bienes_heredados"] = True
        if self._contains_any(q, ("renuncia", "renuncie", "adjudicacion", "division", "liquidacion", "particion")):
            variables["pretension_patrimonial_expresa"] = True
        if self._contains_any(q, ("antes del matrimonio", "antes de casarnos")):
            variables["adquirido_antes_matrimonio"] = True
        if self._contains_any(q, ("durante el matrimonio", "durante el casamiento", "cuando estabamos casados")):
            variables["adquirido_durante_matrimonio"] = True
        if self._contains_any(q, ("herencia", "heredado")):
            variables["origen_herencia"] = True
        if self._contains_any(q, ("compra", "compramos", "compre", "adquirimos")):
            variables["origen_compra"] = True
        if self._contains_any(q, ("ya estamos divorciados", "ya nos divorciamos", "divorcio previo")):
            variables["divorcio_previo"] = True
        if self._contains_any(q, ("de comun acuerdo", "acuerdo", "arreglo")):
            variables["hay_acuerdo"] = True
        if self._contains_any(q, ("conflicto", "no quiere", "se niega", "discusion")):
            variables["hay_conflicto"] = True

        if "no me deja ver" in q:
            variables["impedimento_contacto"] = True

        return variables

    def _build_strategy(self, action: str, v: dict[str, Any]) -> dict[str, Any]:
        if action == "divorcio":
            return self._divorcio_strategy(v)

        if action == "alimentos":
            return self._alimentos_strategy(v)

        if action == "conflicto_patrimonial":
            return self._patrimonial_strategy(v)

        if action == "regimen_comunicacional":
            return self._contacto_strategy()

        return {
            "mensaje": "accion no identificada",
            "confidence": 0.3,
            "validation_notes": ["No se detectaron senales suficientes para una estrategia especifica."],
        }

    def _divorcio_strategy(self, v: dict[str, Any]) -> dict[str, Any]:
        estrategia: dict[str, Any] = {
            "pretension_principal": "divorcio",
            "pretensiones_secundarias": [],
            "parametros": {},
            "confidence": 0.72,
            "validation_notes": [],
        }

        if v.get("hay_bienes"):
            estrategia["pretensiones_secundarias"].append("division_bienes")
            if v.get("bienes_heredados"):
                estrategia["parametros"]["bienes_heredados"] = "bien posiblemente propio; revisar exclusion de la masa ganancial"

        categoria = v.get("categoria_hijo")
        if categoria == "menor_18":
            estrategia["pretensiones_secundarias"].append("alimentos_hijo_menor")
        elif categoria in {"entre_18_y_21", "mayor_21_estudia"}:
            estrategia["pretensiones_secundarias"].append("alimentos_hijo_mayor_condicional")

        return estrategia

    def _alimentos_strategy(self, v: dict[str, Any]) -> dict[str, Any]:
        categoria = str(v.get("categoria_hijo") or "indeterminado")
        estrategia: dict[str, Any] = {
            "pretension_principal": "cuota_alimentaria",
            "pretensiones_secundarias": ["alimentos_provisorios"],
            "parametros": {},
            "preguntas_criticas": [],
            "prueba_sugerida": [],
            "estrategias_bloqueadas": [],
            "urgencia": True,
            "confidence": 0.7,
            "validation_notes": [],
        }

        if categoria == "menor_18":
            estrategia["pretension_principal"] = "cuota_alimentaria_hijo_menor"
            estrategia["parametros"]["encuadre"] = "hijo menor de edad"
            estrategia["parametros"]["porcentaje_estimado"] = "20% - 30%"
            estrategia["confidence"] = 0.9
        elif categoria == "entre_18_y_21":
            estrategia["pretension_principal"] = "cuota_alimentaria_hijo_18_21"
            estrategia["parametros"]["encuadre"] = "hijo entre 18 y 21"
            estrategia["parametros"]["base_legal"] = "deber alimentario aun vigente, sujeto a autonomia progresiva y situacion concreta"
            estrategia["confidence"] = 0.9
        elif categoria == "mayor_21_estudia":
            estrategia["pretension_principal"] = "cuota_alimentaria_hijo_mayor_estudiante"
            estrategia["parametros"]["encuadre"] = "hijo mayor de 21 que estudia"
            estrategia["parametros"]["base_legal"] = "art. 663 CCyC"
            estrategia["prueba_sugerida"].extend([
                "certificado_alumno_regular",
                "plan_de_estudios",
                "comprobantes_de_gastos_actuales",
            ])
            estrategia["confidence"] = 0.94
        elif categoria == "mayor_21_no_estudia":
            estrategia["pretension_principal"] = "analisis_cese_o_limite_cuota_hijo_mayor"
            estrategia["parametros"]["encuadre"] = "hijo mayor de 21 que no estudia"
            estrategia["parametros"]["regla_excluyente"] = "bloquear continuidad automatica por art. 663 CCyC"
            estrategia["estrategias_bloqueadas"].extend([
                "art_663_ccyc",
                "certificado_alumno_regular",
                "continuidad_automatica_de_cuota",
            ])
            estrategia["pretensiones_secundarias"] = ["verificar_autonomia_economica_real"]
            estrategia["confidence"] = 0.95
        else:
            estrategia["preguntas_criticas"].extend([
                "que edad tiene el hijo o hija",
                "estudia actualmente o dejo de estudiar",
                "convive con quien reclama",
                "trabaja o tiene ingresos propios",
            ])
            estrategia["validation_notes"].append("Falta recorte etario o situacion academica para fijar subescenario de alimentos.")

        if v.get("convive"):
            estrategia["parametros"]["convivencia"] = "la convivencia puede reforzar el cuadro de gastos y cuidado cotidiano"
        if v.get("trabaja") or v.get("ingresos_propios"):
            estrategia["parametros"]["autonomia_economica"] = "revisar si existen ingresos propios suficientes antes de sostener aumento o continuidad"
        if v.get("no_trabaja") or v.get("sin_autosustento_laboral"):
            estrategia["parametros"]["autosustento_actual"] = "la falta de empleo actual impide asumir autonomia economica por si sola"
        if v.get("ingresos_negro"):
            estrategia["pretensiones_secundarias"].append("investigacion_patrimonial")
        if v.get("sin_ingresos"):
            estrategia["pretensiones_secundarias"].append("analisis_capacidad_laboral")
        if v.get("sin_ingresos_formales"):
            estrategia["validation_notes"].append("No asumir embargo directo: primero explicar de donde surgirian ingresos o bienes embargables.")

        return estrategia

    def _patrimonial_strategy(self, v: dict[str, Any]) -> dict[str, Any]:
        preguntas = []
        if not v.get("adquirido_antes_matrimonio") and not v.get("adquirido_durante_matrimonio"):
            preguntas.append("el inmueble fue adquirido antes o durante el matrimonio")
        if not v.get("origen_herencia") and not v.get("origen_compra") and not v.get("bienes_heredados"):
            preguntas.append("el bien proviene de herencia o de compra")
        if not v.get("divorcio_previo") and not v.get("vinculo_ex_conyugal"):
            preguntas.append("existe divorcio previo o el vinculo sigue vigente")
        if not v.get("hay_acuerdo") and not v.get("hay_conflicto"):
            preguntas.append("hay acuerdo para adjudicar o existe conflicto")

        return {
            "pretension_principal": "definicion_patrimonial_sobre_inmueble",
            "pretensiones_secundarias": [
                "determinar_si_el_bien_es_ganancial_o_propio",
                "evaluar_convenio_de_adjudicacion_o_liquidacion",
                "analizar_particion_o_reglas_de_condominio",
            ],
            "parametros": {
                "conflicto_detectado": "cotitularidad o disputa patrimonial sobre inmueble con ex conyuge",
                "salida_no_generica": "antes de hablar de renuncia hay que definir titulo, origen del bien y marco de liquidacion",
                "orientacion_estrategica_minima": [
                    "explorar convenio de adjudicacion si hay acuerdo suficiente",
                    "evaluar liquidacion de comunidad o gananciales si el bien integra esa masa",
                    "considerar particion o reglas de condominio si la disputa pasa por cotitularidad",
                ],
            },
            "preguntas_criticas": preguntas,
            "confidence": 0.92,
            "validation_notes": [
                "No usar fallback generico: el caso muestra un conflicto patrimonial concreto.",
            ],
        }

    def _contacto_strategy(self) -> dict[str, Any]:
        return {
            "pretension_principal": "fijacion_regimen_comunicacional",
            "pretensiones_secundarias": ["medida_urgente", "audiencia"],
            "urgencia": True,
            "confidence": 0.85,
            "validation_notes": [],
        }

    def _validate_strategy(self, action: str, v: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
        notes = [str(item).strip() for item in (strategy.get("validation_notes") or []) if str(item).strip()]

        if action == "alimentos":
            blocked = set(strategy.get("estrategias_bloqueadas") or [])
            pruebas = [str(item).strip() for item in (strategy.get("prueba_sugerida") or []) if str(item).strip()]

            if v.get("hijo_no_estudia"):
                if "certificado_alumno_regular" in pruebas:
                    pruebas = [item for item in pruebas if item != "certificado_alumno_regular"]
                    notes.append("Se elimino prueba academica incompatible porque la consulta dice que no estudia.")
                blocked.update({"certificado_alumno_regular", "art_663_ccyc"})

            if v.get("sin_ingresos_formales"):
                notes.append("Se baja la confianza para evitar asumir embargo directo sin base sobre ingresos formales.")
                strategy["confidence"] = min(float(strategy.get("confidence") or 0.7), 0.68)

            strategy["prueba_sugerida"] = pruebas
            strategy["estrategias_bloqueadas"] = sorted(blocked)

        strategy["validation_notes"] = notes
        return strategy

    def _categorize_child_support(self, variables: dict[str, Any]) -> str | None:
        if variables.get("hay_multiples_edades"):
            categorias = variables.get("categorias_etarias_detectadas") or []
            if len(categorias) > 1:
                return None
        edad = variables.get("edad_relevante")
        if not isinstance(edad, int):
            return None
        if edad < 18:
            return "menor_18"
        if edad <= 21:
            return "entre_18_y_21"
        if variables.get("hijo_no_estudia"):
            return "mayor_21_no_estudia"
        if variables.get("hijo_estudia"):
            return "mayor_21_estudia"
        return "mayor_21_indeterminado"

    def _is_patrimonial_conflict(self, q: str) -> bool:
        score = 0
        if self._contains_any(q, ("cotitularidad", "cotitular", "condominio")):
            score += 2
        if self._contains_any(q, ("casa", "inmueble", "vivienda", "propiedad")):
            score += 1
        if self._contains_any(q, ("ex esposo", "exesposo", "ex esposa", "exesposa", "divorcio")):
            score += 1
        if self._contains_any(q, ("division", "adjudicacion", "renuncia", "liquidacion", "particion")):
            score += 1
        if "hered" in q:
            score += 1
        return score >= 3

    def _contains_any(self, q: str, terms: tuple[str, ...]) -> bool:
        return any(term in q for term in terms)

    def _categorize_age_buckets(self, edades: list[int]) -> list[str]:
        buckets: list[str] = []
        if any(edad < 18 for edad in edades):
            buckets.append("menor_18")
        if any(18 <= edad <= 21 for edad in edades):
            buckets.append("entre_18_y_21")
        if any(edad > 21 for edad in edades):
            buckets.append("mayor_21")
        return buckets
