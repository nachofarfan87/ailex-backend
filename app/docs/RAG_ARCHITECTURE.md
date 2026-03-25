# AILEX — Arquitectura RAG Jurídica

## Visión General

Sistema de recuperación documental **jurídico** (no genérico) orientado a litigación y redacción procesal en Jujuy, Argentina.

```
Documento → Ingestión → Chunks + Embeddings → Store
                                                 ↑
Consulta → Filtros → Búsqueda Híbrida → Re-Rank → Contexto Trazable
```

---

## Pipeline de Ingestión

```
Archivo (PDF/DOCX/TXT) o texto manual
        │
        ▼
  TextExtractor          ← pdfplumber / python-docx / txt
        │
        ▼
  NormalizationService   ← limpieza, detección de entidades
        │
        ▼
  LegalChunker           ← particionado por artículos/secciones/párrafos
        │
        ▼
  EmbeddingGenerator     ← sentence-transformers (multilingual)
        │
        ▼
  DocumentStore          ← almacenamiento (memoria / PostgreSQL)
```

### Chunking Jurídico

Preserva:
- Artículos (`Art. 123`, `ARTÍCULO 123 bis`)
- Títulos y capítulos
- Sumarios de jurisprudencia
- Partes resolutivas
- Párrafos argumentales completos

**No fragmenta** citas legales ni artículos con sus incisos.

---

## Búsqueda Híbrida

Tres señales combinadas con pesos:

| Señal | Peso | Método |
|---|---|---|
| Semántica | 0.45 | Cosine similarity (embeddings) |
| Keyword | 0.25 | BM25-like scoring |
| Jurídica | 0.30 | Ponderación por jerarquía+jurisdicción+materia |

### Ponderación Jurídica

| Jerarquía | Peso | Ejemplo |
|---|---|---|
| Normativa | 1.0 | Códigos, leyes, acordadas |
| Jurisprudencia | 0.85 | Fallos, sentencias |
| Doctrina | 0.55 | Tratados, artículos |
| Interno | 0.30 | Escritos del estudio |

**Bonus**: +0.25 por jurisdicción exacta, +0.20 por materia.

---

## Tipos de Fuente

| Tipo | Jerarquía | Autoridad | Uso |
|---|---|---|---|
| codigo | normativa | vinculante | Citación directa |
| ley | normativa | vinculante | Citación directa |
| reglamento | normativa | vinculante | Citación directa |
| acordada | normativa | cuasi_vinculante | Citación directa |
| jurisprudencia | jurisprudencia | persuasivo | Precedente argumental |
| doctrina | doctrina | persuasivo | Apoyo teórico |
| escrito | interno | referencial | Patrón argumental |
| modelo | interno | referencial | Base para generación |
| estrategia | interno | referencial | Referencia interna |

> Material interno puede usarse como **patrón argumental** pero NO como autoridad normativa.

---

## API Endpoints

### Documentos

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/documents/upload` | Cargar archivo (PDF/DOCX/TXT) |
| POST | `/api/documents/upload/text` | Cargar texto manual |
| GET | `/api/documents/` | Listar documentos con filtros |
| GET | `/api/documents/stats` | Estadísticas de la base |
| GET | `/api/documents/{id}` | Detalle de documento |
| GET | `/api/documents/{id}/chunks` | Chunks con metadata |
| DELETE | `/api/documents/{id}` | Eliminar documento |

### Búsqueda

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/search/` | Búsqueda híbrida |
| POST | `/api/search/context` | Contexto trazable para RAG |

---

## Metadatos

### Por documento
document_id, title, source_type, source_hierarchy, authority_level,
jurisdiction, court, legal_area, fuero, document_date,
reliability_score, origin, tags, status, chunk_count, total_chars

### Por chunk
chunk_id, document_id, text, embedding, chunk_index,  
section, article_reference, page_number, char_count,
source_type, source_hierarchy, jurisdiction, legal_area

---

## Archivos

| Archivo | Función |
|---|---|
| `db/models.py` | SourceDocument, DocumentChunk + enums |
| `db/store.py` | Almacén en memoria (dev) |
| `modules/ingestion/extractor.py` | Extracción de texto |
| `modules/ingestion/chunker.py` | Chunking jurídico |
| `modules/ingestion/embedder.py` | Generación de embeddings |
| `modules/ingestion/service.py` | Orquestador del pipeline |
| `modules/search/service.py` | Búsqueda híbrida + re-ranking |
| `api/routes/documents.py` | API de documentos |
| `api/routes/search.py` | API de búsqueda |
