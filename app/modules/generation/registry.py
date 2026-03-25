"""
AILEX — Registro de plantillas de escritos jurídicos.

Punto de acceso centralizado para:
- Consultar plantillas por tipo de escrito
- Listar plantillas disponibles (con filtros opcionales)
- Obtener metadatos de placeholders requeridos

El registro es de solo lectura en runtime.
Las plantillas se agregan en templates.py.
"""

from app.modules.generation.schemas import TemplateMetadata
from app.modules.generation.templates import TEMPLATES, VARIANTES_VALIDAS, _normalizar_variante


class TemplateRegistry:
    """
    Registro centralizado de plantillas jurídicas.

    Provee acceso a las plantillas definidas en templates.py
    con métodos de búsqueda y filtrado.
    """

    @staticmethod
    def get(tipo_escrito: str) -> TemplateMetadata | None:
        """
        Obtener la metadata de una plantilla por tipo de escrito.
        Retorna None si el tipo no está registrado.
        """
        return TEMPLATES.get(tipo_escrito.lower().replace("-", "_").replace(" ", "_"))

    @staticmethod
    def list_all() -> list[TemplateMetadata]:
        """Listar todas las plantillas disponibles."""
        return list(TEMPLATES.values())

    @staticmethod
    def list_by_fuero(fuero: str) -> list[TemplateMetadata]:
        """
        Listar plantillas compatibles con un fuero.
        Incluye plantillas de fuero 'general' (aplican a todos).
        """
        fuero_norm = fuero.lower()
        return [
            t for t in TEMPLATES.values()
            if t.fuero == fuero_norm or t.fuero == "general"
        ]

    @staticmethod
    def list_by_materia(materia: str) -> list[TemplateMetadata]:
        """
        Listar plantillas compatibles con una materia.
        Incluye plantillas de materia 'general'.
        """
        materia_norm = materia.lower()
        return [
            t for t in TEMPLATES.values()
            if t.materia == materia_norm or t.materia == "general"
        ]

    @staticmethod
    def list_filtered(fuero: str = None, materia: str = None) -> list[TemplateMetadata]:
        """
        Listar plantillas aplicando filtros opcionales de fuero y materia.
        Si ambos son None, retorna todas.
        """
        results = list(TEMPLATES.values())
        if fuero:
            fuero_norm = fuero.lower()
            results = [
                t for t in results
                if t.fuero == fuero_norm or t.fuero == "general"
            ]
        if materia:
            materia_norm = materia.lower()
            results = [
                t for t in results
                if t.materia == materia_norm or t.materia == "general"
            ]
        return results

    @staticmethod
    def get_tipos_disponibles() -> list[str]:
        """Listar los tipos de escrito disponibles."""
        return list(TEMPLATES.keys())

    @staticmethod
    def get_variantes_disponibles() -> list[str]:
        """Listar las variantes de redacción disponibles."""
        return VARIANTES_VALIDAS

    @staticmethod
    def normalizar_variante(variante: str) -> str:
        """Normalizar el nombre de una variante (compatibilidad con nombres anteriores)."""
        return _normalizar_variante(variante)

    @staticmethod
    def get_placeholders_requeridos(tipo_escrito: str) -> list[str] | None:
        """
        Obtener los placeholders requeridos de una plantilla.
        Retorna None si el tipo no existe.
        """
        tmpl = TemplateRegistry.get(tipo_escrito)
        if tmpl is None:
            return None
        return tmpl.placeholders_requeridos

    @staticmethod
    def get_checklist(tipo_escrito: str) -> list[str] | None:
        """
        Obtener el checklist previo de una plantilla.
        Retorna None si el tipo no existe.
        """
        tmpl = TemplateRegistry.get(tipo_escrito)
        if tmpl is None:
            return None
        return tmpl.checklist_previo

    @staticmethod
    def to_summary_dict(tmpl: TemplateMetadata) -> dict:
        """
        Convertir una plantilla a dict de resumen para listados.
        No incluye el texto de la plantilla (solo metadatos).
        """
        return {
            "id": tmpl.id,
            "nombre": tmpl.nombre,
            "tipo_escrito": tmpl.tipo_escrito,
            "fuero": tmpl.fuero,
            "materia": tmpl.materia,
            "version": tmpl.version,
            "variantes_permitidas": tmpl.variantes_permitidas,
            "estructura_base": tmpl.estructura_base,
            "placeholders_requeridos_count": len(tmpl.placeholders_requeridos),
            "placeholders_opcionales_count": len(tmpl.placeholders_opcionales),
        }
