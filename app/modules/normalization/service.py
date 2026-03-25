"""
AILEX — Módulo de Normalización de Entrada.

Capa de preprocesamiento antes del análisis jurídico.
Limpia, clasifica y extrae entidades del texto de entrada.
"""

import re


class NormalizationService:
    """
    Servicio de normalización de entrada.

    Pipeline:
    1. Limpieza de texto (espacios, caracteres especiales)
    2. Detección de idioma / formato
    3. Extracción de entidades básicas (fechas, expedientes, partes)
    4. Clasificación preliminar del tipo de documento
    """

    # Patrones comunes en textos judiciales argentinos
    PATTERNS = {
        "expediente": re.compile(
            r"[Ee]xp(?:te)?\.?\s*[Nn]?[°ºo]?\s*(\d+[\-/]\d+)", re.UNICODE
        ),
        "fecha": re.compile(
            r"(\d{1,2})\s*(?:de\s+)?(\w+)\s*(?:de\s+)?(\d{4})", re.UNICODE
        ),
        "articulo": re.compile(
            r"[Aa]rt(?:ículo)?\.?\s*(\d+)", re.UNICODE
        ),
        "caratula": re.compile(
            r'"([^"]+)"\s*[Ss]/\s*(.+)', re.UNICODE
        ),
    }

    async def normalize(self, text: str) -> dict:
        """
        Normalizar texto de entrada.

        Retorna:
        - text_clean: texto limpiado
        - entities: entidades extraídas
        - doc_type: tipo de documento detectado (si aplica)
        """
        text_clean = self._clean_text(text)
        entities = self._extract_entities(text_clean)

        return {
            "text_clean": text_clean,
            "entities": entities,
            "doc_type": self._classify_document(text_clean),
        }

    def _clean_text(self, text: str) -> str:
        """Limpieza básica de texto preservando estructura de líneas.

        IMPORTANTE: No colapsamos saltos de línea (\n) porque el chunker jurídico
        depende de ellos para detectar artículos con re.MULTILINE.
        Solo normalizamos espacios y tabulaciones horizontales.
        """
        # Normalizar finales de línea para que el chunker opere siempre sobre \n
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Normalizar espacios y tabs horizontales (NO saltos de línea)
        text = re.sub(r'[^\S\n]+', ' ', text)
        # Reducir 3+ líneas en blanco a 2 (preservar separación de secciones)
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Normalizar comillas tipográficas
        text = text.replace('\u201c', '"').replace('\u201d', '"')
        return text.strip()

    def _extract_entities(self, text: str) -> dict:
        """Extraer entidades jurídicas básicas."""
        entities = {}

        for name, pattern in self.PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                entities[name] = matches

        return entities

    def _classify_document(self, text: str) -> str:
        """
        Clasificación preliminar del tipo de documento.

        TODO: Mejorar con NLP / modelo entrenado.
        """
        text_lower = text.lower()

        if "notifíquese" in text_lower or "notifícase" in text_lower:
            return "notificacion"
        elif "sentencia" in text_lower and "resuelve" in text_lower:
            return "sentencia"
        elif "demanda" in text_lower:
            return "demanda"
        elif "contestación" in text_lower or "contesta" in text_lower:
            return "contestacion"
        elif "recurso" in text_lower:
            return "recurso"

        return "desconocido"
