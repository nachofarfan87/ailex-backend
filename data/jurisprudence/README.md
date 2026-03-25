# Corpus Jurisprudencial Local - AILEX

## Estructura

Directorio base:

```text
backend/data/jurisprudence/
```

Archivos cargables por el corpus:
- `csjn.json`
- `camaras_nacionales.json`
- `tribunales_provinciales.json`
- cualquier otro `*.json` curado dentro de este directorio

Archivos no cargables:
- `templates/*.template.json`
- `templates/*.md`

## Capas de dataset

- `real`: solo casos efectivamente verificados y aprobados.
- `seed`: semillas editoriales o ejemplos internos. No deben usarse como corpus productivo.
- `fixture`: solo pruebas automáticas.

## Esquema operativo vigente

Campos estructurales:
- `case_id`
- `court`
- `jurisdiction`
- `forum`
- `year`
- `case_name`
- `source`
- `source_url`
- `legal_issue`
- `facts_summary`
- `decision_summary`
- `key_reasoning`
- `holding`
- `outcome`
- `topics`
- `keywords`
- `applied_articles`
- `procedural_stage`
- `document_type`
- `action_slug`
- `strategic_value`
- `territorial_priority`
- `local_practice_value`
- `court_level`
- `redundancy_group`
- `practical_frequency`
- `local_topic_cluster`

Campos auxiliares:
- `chamber`
- `date`
- `parties`
- `full_text`
- `dataset_kind`
- `metadata`

## Regla de admisión para `dataset_kind=real`

Además del esquema general, un registro real debe incluir metadata obligatoria:

- `metadata.verification_status=verified`
- `metadata.curation_status=approved`
- `metadata.verified_at`
- `metadata.verified_by`
- `metadata.curated_by`
- `metadata.source_reference`

Si falta eso, el caso puede existir como borrador editorial, pero no debe entrar como
corpus real aprobado.

Para la linea editorial Jujuy se exigen ademas:
- `territorial_priority`
- `local_practice_value`
- `court_level`
- `redundancy_group`
- `practical_frequency`
- `local_topic_cluster`

## Flujo recomendado

1. Curar el caso en ficha editorial.
2. Pasarlo a JSON estructurado.
3. Validarlo con:

```powershell
python backend/scripts/validate_jurisprudence_corpus.py
```

4. Recién entonces marcarlo como `dataset_kind=real`.

## Criterios de exclusión

- Fallos redundantes sin aporte estratégico diferencial.
- Resúmenes pobres o puramente administrativos.
- Casos sin holding claro.
- Fuentes no verificables.
- Casos con placeholders, texto de ejemplo o campos débiles.

## Documentación operativa

- Guía de curación: `backend/data/jurisprudence/CURATION_README.md`
- Guía local Jujuy: `backend/data/jurisprudence/JUJUY_SUBCORPUS_README.md`
- Plantilla JSON: `backend/data/jurisprudence/templates/curated_real_case.template.json`
- Plantilla Jujuy: `backend/data/jurisprudence/templates/jujuy_local_case.template.json`
- Ficha editorial: `backend/data/jurisprudence/templates/curation_case_sheet.md`
