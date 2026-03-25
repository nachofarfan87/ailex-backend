"""
AILEX — Catálogo mínimo de opciones estratégicas prudentes.
"""

from app.modules.strategy.schemas import StrategyContext


def build_candidate_options(context: StrategyContext) -> list[dict]:
    text = context.text_clean.casefold()
    stage = (context.etapa_procesal or "").casefold()
    goal = (context.objetivo_abogado or "").casefold()
    actions = {
        (item.get("tipo") or "").casefold()
        for item in context.actuaciones_detectadas
    }
    deadline_types = {
        (item.get("tipo_actuacion") or "").casefold()
        for item in context.plazos_detectados
    }
    findings = " ".join(context.hallazgos_revision).casefold()

    candidates = []

    def add_option(
        nombre: str,
        trigger: str,
        justificacion: str,
        requisitos: list[str],
        ventajas: list[str],
        riesgos: list[str],
    ):
        if any(option["nombre"] == nombre for option in candidates):
            return
        candidates.append(
            {
                "nombre": nombre,
                "trigger": trigger,
                "justificacion": justificacion,
                "requisitos": requisitos,
                "ventajas": ventajas,
                "riesgos": riesgos,
            }
        )

    if (
        "traslado" in actions
        or "plazo_para_contestar" in deadline_types
        or "traslado" in text
        or "traslado" in stage
    ):
        add_option(
            "contestar traslado",
            "explicit",
            "El caso muestra un traslado o plazo de respuesta que podría requerir una contestación o planteo inicial.",
            [
                "Texto completo del traslado o demanda",
                "Fecha de notificación efectiva",
                "Definir si hay excepciones o defensa de fondo",
            ],
            [
                "Permite responder dentro de la ventana procesal conocida",
                "Ordena tempranamente la posición defensiva del cliente",
            ],
            [
                "Puede ser prematuro si aún faltan constancias o documentación crítica",
                "Una contestación incompleta puede cerrar líneas defensivas",
            ],
        )
        add_option(
            "reservar planteo",
            "inferred",
            "Si el traslado exige reacción rápida pero la base documental es incompleta, puede convenir reservar defensas o agravios para una oportunidad mejor definida.",
            [
                "Identificar qué punto conviene reservar y por qué",
                "Verificar si la vía procesal admite reserva sin preclusión",
            ],
            [
                "Evita fijar prematuramente una posición sin datos suficientes",
                "Mantiene margen para ajustar argumentos cuando aparezca más documentación",
            ],
            [
                "La reserva puede ser insuficiente si el planteo debía introducirse de inmediato",
                "Exige revisar con cuidado la carga procesal aplicable",
            ],
        )
        if "incomplet" in text or "document" in text or "constancia" in text:
            add_option(
                "esperar constancia o documentación antes de actuar",
                "suggested",
                "Si el traslado ya fue advertido pero todavía faltan piezas o constancias relevantes, puede ser útil medir el costo de esperar una base documental más clara.",
                [
                    "Precisar qué documentación falta y si su ausencia impide una respuesta responsable",
                    "Controlar que la espera no consuma una oportunidad procesal relevante",
                ],
                [
                    "Evita definir una táctica con información incompleta",
                    "Permite comparar mejor defensa inmediata versus respuesta diferida",
                ],
                [
                    "Puede ser riesgoso si el plazo corre y la documentación no aparece a tiempo",
                    "Exige monitoreo activo para no perder la oportunidad de responder",
                ],
            )

    if (
        "intimacion" in actions
        or "intimar" in goal
        or "cobro" in goal
        or "intim" in text
    ):
        add_option(
            "intimar previamente",
            "explicit",
            "La situación permite considerar una intimación previa para robustecer el registro de incumplimiento o forzar regularización.",
            [
                "Definir objeto concreto de la intimación",
                "Contar con domicilio o canal de notificación verificable",
            ],
            [
                "Puede ordenar el conflicto antes de escalarlo procesalmente",
                "Genera constancia útil para un paso posterior",
            ],
            [
                "Puede agregar demora si la urgencia exige otra vía",
                "Una intimación mal formulada aporta poco valor táctico",
            ],
        )

    if "subsan" in findings or "subsan" in text or "subsan" in stage or "defecto" in findings or "observad" in text:
        add_option(
            "subsanar presentación",
            "explicit",
            "Hay señales de defectos u observaciones que podrían permitir corrección antes de avanzar por una vía más agresiva.",
            [
                "Identificar el defecto concreto observado",
                "Confirmar si existe plazo o forma de subsanación",
            ],
            [
                "Reduce riesgo de rechazo formal inmediato",
                "Ordena la pieza antes de discutir el fondo",
            ],
            [
                "Puede no alcanzar si el defecto es sustancial",
                "Exige revisar si subsanar implica reformular parte del planteo",
            ],
        )
        add_option(
            "reformular escrito",
            "inferred",
            "Si los defectos afectan la estrategia de fondo, puede ser más prudente reformular la presentación y no solo corregir el detalle observado.",
            [
                "Determinar alcance de la reformulación necesaria",
                "Verificar impacto sobre plazos y preclusiones",
            ],
            [
                "Permite alinear forma, hechos y pedido en una sola versión consistente",
                "Evita insistir sobre una base argumental débil",
            ],
            [
                "Puede demandar más tiempo y documentación",
                "No siempre es viable si la etapa procesal ya está avanzada",
            ],
        )

    if "pronto despacho" in text or "demora" in text or "despacho" in goal or "demora" in stage:
        add_option(
            "solicitar pronto despacho",
            "explicit",
            "La demora relatada admite evaluar un pronto despacho como vía para activar el trámite sin avanzar todavía sobre un recurso más intenso.",
            [
                "Constancia objetiva de la demora",
                "Identificar qué acto o resolución se encuentra pendiente",
            ],
            [
                "Puede reactivar el expediente con bajo costo táctico",
                "Ordena el reclamo frente a la inactividad",
            ],
            [
                "Pierde fuerza si no hay demora documentada",
                "Puede ser prematuro si aún no venció un plazo razonable de despacho",
            ],
        )
        add_option(
            "esperar constancia o documentación antes de actuar",
            "suggested",
            "Si la demora o el estado del trámite no están acreditados, puede ser más prudente esperar constancia suficiente antes de impulsar una medida.",
            [
                "Obtener pase, cargo, despacho pendiente o informe de mesa de entradas",
            ],
            [
                "Evita impulsar una medida sobre una base fáctica incompleta",
                "Permite comparar mejor costo táctico y utilidad real del próximo paso",
            ],
            [
                "Puede consumir tiempo útil si el expediente realmente está paralizado",
                "Exige control activo para no perder oportunidades",
            ],
        )

    if (
        "apel" in text
        or "sentencia" in text
        or "resoluci" in text
        or "recurso" in text
        or "resoluci" in stage
        or "recurso" in stage
    ):
        add_option(
            "apelar",
            "explicit",
            "Si la pieza o situación revela una resolución adversa, la apelación aparece como una vía a considerar, siempre sujeta a admisibilidad y plazo.",
            [
                "Texto completo de la resolución o sentencia",
                "Fecha de notificación",
                "Identificar agravios concretos",
            ],
            [
                "Abre revisión de la decisión cuestionada",
                "Permite ordenar agravios y preservar revisión ulterior",
            ],
            [
                "Puede ser inadmisible si la resolución no es recurrible",
                "Un agravio genérico debilita la utilidad del recurso",
            ],
        )

    if "cautelar" in goal or "urgenc" in text or "embargo" in text:
        add_option(
            "promover medida cautelar",
            "suggested",
            "Si la urgencia o el riesgo de frustración aparece en el caso, puede evaluarse una medida cautelar como opción ofensiva prudente.",
            [
                "Acreditar verosimilitud del derecho y peligro en la demora",
                "Definir el alcance concreto de la tutela solicitada",
            ],
            [
                "Protege la utilidad práctica de la pretensión principal",
                "Puede ordenar tempranamente el terreno de litigio",
            ],
            [
                "Sin base fáctica o documental suficiente puede exponerse a rechazo",
                "Requiere especial prudencia para no sobredimensionar la urgencia",
            ],
        )

    if "prueba" in goal or "prueba" in text:
        add_option(
            "ampliar prueba",
            "suggested",
            "Cuando el objetivo es robustecer la posición del cliente, ampliar o asegurar prueba puede ser una vía intermedia razonable.",
            [
                "Precisar qué prueba falta y para qué punto controvertido",
                "Verificar si la etapa procesal aún lo permite",
            ],
            [
                "Mejora la base de decisión antes de un planteo más agresivo",
                "Reduce dependencia de inferencias débiles",
            ],
            [
                "Puede ser improcedente si la etapa probatoria está cerrada",
                "Sin foco claro puede diluir la estrategia",
            ],
        )

    if not candidates:
        add_option(
            "esperar constancia o documentación antes de actuar",
            "suggested",
            "Con la información actual, una vía prudente es completar el cuadro fáctico antes de definir un paso procesal irreversible.",
            [
                "Obtener pieza completa, resolución, constancia o fecha relevante",
            ],
            [
                "Evita decisiones tácticas apoyadas en una base incompleta",
            ],
            [
                "Demora la adopción de una vía concreta",
            ],
        )

    return candidates
