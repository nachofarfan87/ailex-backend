"""
AILEX — Chunking jurídico.

Particionado de documentos legales preservando:
- artículos y sus incisos
- sumarios de jurisprudencia
- párrafos argumentales completos
- resoluciones y dispositivos
- citas legales íntegras

NO es un chunker genérico — está diseñado para documentos
jurídicos argentinos.
"""

import re
from dataclasses import dataclass, field


@dataclass
class LegalChunk:
    """Un fragmento jurídico con metadata de posición."""
    text: str
    index: int
    section: str = ""
    article_reference: str = ""
    page_number: int = None
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.text)


class LegalChunker:
    """
    Particionador de textos jurídicos.

    Estrategia:
    1. Detectar encabezados y artículos
    2. Dividir por secciones jurídicas
    3. Para textos largos sin estructura: chunks por párrafo con overlap
    4. Nunca fragmentar en medio de una cita legal
    """

    # Tamaños de chunk
    MIN_CHUNK_SIZE = 200       # mínimo para que un chunk tenga valor
    TARGET_CHUNK_SIZE = 1200   # tamaño objetivo
    MAX_CHUNK_SIZE = 2000      # máximo antes de forzar split
    OVERLAP_SIZE = 150         # overlap entre chunks consecutivos

    # ─── Patrones jurídicos argentinos ──────────────────────

    # Artículos: "Art. 123", "Artículo 123", "ARTICULO 123", "Art° 12", etc.
    # \s* al inicio tolera espacios/tabs de PDF (common en texto extraído)
    ARTICLE_PATTERN = re.compile(
        r'^\s*(?:art(?:[ií]culo)?|art\.)\s*'
        r'(\d+[A-Za-z0-9°º]*(?:\s*(?:bis|ter|quater|quinquies))?)'
        r'\s*(?:[-.:)]\s*)?',
        re.IGNORECASE | re.MULTILINE
    )

    # Incisos: "a)", "1)", "I.", "inc. a)"
    INCISO_PATTERN = re.compile(
        r'^\s*(?:(?:inc\.?\s*)?[a-z]\)|(?:\d+\))|(?:[IVX]+\.))',
        re.MULTILINE
    )

    # Títulos y capítulos (incluye PARTE PRIMERA/SEGUNDA usados en constituciones)
    TITLE_PATTERN = re.compile(
        r'^\s*(?:T[ÍI]TULO|CAP[ÍI]TULO|SECCI[ÓO]N|LIBRO|PARTE)\s+[IVXLCDM\d]+',
        re.IGNORECASE | re.MULTILINE
    )

    # Encabezados de secciones procesales
    SECTION_PATTERN = re.compile(
        r'^(?:I+[.-]|[IVX]+[.-]|\d+[.-])\s+[A-ZÁÉÍÓÚÑ]',
        re.MULTILINE
    )

    # Sumarios / voces de jurisprudencia
    SUMARIO_PATTERN = re.compile(
        r'^(?:SUMARIO|VOCES?|RESUMEN|DOCTRINA DEL FALLO)',
        re.IGNORECASE | re.MULTILINE
    )

    # Parte resolutiva
    RESOLUTIVA_PATTERN = re.compile(
        r'^(?:RESUELVE|RESOLUCI[ÓO]N|SENTENCIA|FALLO|SE RESUELVE)',
        re.IGNORECASE | re.MULTILINE
    )

    # Tipos normativos — usan estrategia article-first
    NORMATIVE_SOURCE_TYPES = {
        "codigo", "ley", "reglamento", "acordada",
        "constitucion", "decreto",
    }

    def chunk(
        self,
        text: str,
        page_map: dict = None,
        source_type: str = None,
    ) -> list["LegalChunk"]:
        """
        Particionar un texto jurídico en chunks.

        Args:
            text: texto completo del documento
            page_map: opcional, mapeo de posición → número de página
            source_type: opcional, tipo de fuente (ej. 'codigo', 'ley')
                         Si es normativa, se fuerza artículo como estrategia primaria.

        Returns:
            Lista de LegalChunk ordenados
        """
        if not text or len(text.strip()) < self.MIN_CHUNK_SIZE:
            if text and text.strip():
                return [LegalChunk(text=text.strip(), index=0)]
            return []

        is_normative = (
            source_type is not None
            and source_type.lower() in self.NORMATIVE_SOURCE_TYPES
        )

        # Para fuentes normativas, intentar siempre por artículos primero
        # incluso si hay pocos (umbral más bajo)
        article_chunks = self._split_by_articles(text, min_matches=2)
        if article_chunks:
            return self._finalize_chunks(
                article_chunks,
                page_map,
                preserve_small_chunks=is_normative,
            )

        # Si no hay artículos, intentar por secciones / capítulos
        section_chunks = self._split_by_sections(text)
        if section_chunks:
            return self._finalize_chunks(section_chunks, page_map)

        # Fallback: particionado por párrafos con overlap
        para_chunks = self._split_by_paragraphs(text)
        return self._finalize_chunks(para_chunks, page_map)

    def _split_by_articles(self, text: str, min_matches: int = 2) -> list[dict]:
        """Dividir por artículos (para códigos y leyes)."""
        matches = list(self.ARTICLE_PATTERN.finditer(text))
        if len(matches) < min_matches:
            return []

        chunks = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk_text = text[start:end].strip()

            if chunk_text:
                article_ref = f"Art. {match.group(1)}" if match.group(1) else ""
                chunks.append({
                    "text": chunk_text,
                    "section": article_ref,
                    "article_reference": article_ref,
                    "start_pos": start,
                })

        return chunks

    def _split_by_sections(self, text: str) -> list[dict]:
        """Dividir por secciones (para escritos, sentencias)."""
        # Combinar patrones de sección
        all_splits = []

        for pattern in [self.TITLE_PATTERN, self.SECTION_PATTERN,
                        self.SUMARIO_PATTERN, self.RESOLUTIVA_PATTERN]:
            for match in pattern.finditer(text):
                all_splits.append((match.start(), match.group().strip()))

        if len(all_splits) < 2:
            return []

        # Ordenar por posición
        all_splits.sort(key=lambda x: x[0])

        chunks = []
        for i, (start, section_name) in enumerate(all_splits):
            end = all_splits[i + 1][0] if i + 1 < len(all_splits) else len(text)
            chunk_text = text[start:end].strip()

            if len(chunk_text) > self.MAX_CHUNK_SIZE:
                # Sub-dividir secciones largas
                sub_chunks = self._split_by_paragraphs(chunk_text)
                for sc in sub_chunks:
                    sc["section"] = section_name
                chunks.extend(sub_chunks)
            elif chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "section": section_name,
                    "article_reference": "",
                    "start_pos": start,
                })

        return chunks

    def _split_by_paragraphs(self, text: str) -> list[dict]:
        """
        Fallback: dividir por párrafos con overlap.
        Preserva párrafos completos, no corta en medio.
        """
        # Dividir en párrafos (doble salto de línea)
        paragraphs = re.split(r'\n\s*\n', text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks = []
        current_text = ""
        current_start = 0

        for para in paragraphs:
            # Si agregar este párrafo excede el máximo, cerrar chunk
            if (current_text
                    and len(current_text) + len(para) > self.TARGET_CHUNK_SIZE):
                chunks.append({
                    "text": current_text.strip(),
                    "section": "",
                    "article_reference": "",
                    "start_pos": current_start,
                })
                # Overlap: mantener el último párrafo del chunk anterior
                overlap_text = current_text.split("\n\n")[-1] if "\n\n" in current_text else ""
                if len(overlap_text) <= self.OVERLAP_SIZE:
                    current_text = overlap_text + "\n\n" + para
                else:
                    current_text = para
                current_start = text.find(para, current_start)
            else:
                if not current_text:
                    current_start = text.find(para)
                current_text += ("\n\n" if current_text else "") + para

        # Último chunk
        if current_text.strip():
            chunks.append({
                "text": current_text.strip(),
                "section": "",
                "article_reference": "",
                "start_pos": current_start,
            })

        return chunks

    def _finalize_chunks(
        self,
        raw_chunks: list[dict],
        page_map: dict = None,
        preserve_small_chunks: bool = False,
    ) -> list[LegalChunk]:
        """Convertir chunks crudos a LegalChunk con metadata."""
        final = []
        for i, chunk in enumerate(raw_chunks):
            text = chunk["text"]

            # Filtrar chunks muy pequeños
            if (
                not preserve_small_chunks
                and len(text) < self.MIN_CHUNK_SIZE
                and len(raw_chunks) > 1
            ):
                # Intentar fusionar con el siguiente
                if i + 1 < len(raw_chunks):
                    raw_chunks[i + 1]["text"] = text + "\n\n" + raw_chunks[i + 1]["text"]
                    continue
                # O con el anterior
                elif final:
                    final[-1].text += "\n\n" + text
                    final[-1].char_count = len(final[-1].text)
                    continue

            page = None
            if page_map and "start_pos" in chunk:
                # Buscar página correspondiente
                for pos, pg in sorted(page_map.items()):
                    if chunk["start_pos"] >= int(pos):
                        page = pg

            legal_chunk = LegalChunk(
                text=text,
                index=len(final),
                section=chunk.get("section", ""),
                article_reference=chunk.get("article_reference", ""),
                page_number=page,
            )
            final.append(legal_chunk)

        return final

    def detect_legal_headers(self, text: str) -> list[dict]:
        """
        Detectar encabezados jurídicos en un texto.
        Retorna lista de headers con posición y tipo.
        """
        headers = []

        for match in self.ARTICLE_PATTERN.finditer(text):
            headers.append({
                "type": "article", "text": match.group(),
                "position": match.start(),
            })

        for match in self.TITLE_PATTERN.finditer(text):
            headers.append({
                "type": "title", "text": match.group(),
                "position": match.start(),
            })

        for match in self.RESOLUTIVA_PATTERN.finditer(text):
            headers.append({
                "type": "resolutiva", "text": match.group(),
                "position": match.start(),
            })

        headers.sort(key=lambda h: h["position"])
        return headers
