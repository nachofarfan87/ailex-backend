# Operativa de Curación Jurisprudencial - AILEX

## Objetivo

Convertir una fuente bruta en un caso jurisprudencial usable por AILEX sin perder
trazabilidad, verificabilidad ni utilidad procesal.

## Flujo operativo

1. Selección de fuente bruta
- Priorizar fuentes oficiales o bases institucionales estables.
- Excluir blogs, reposts sin trazabilidad o resúmenes sin texto verificable.

2. Lectura jurídica
- Confirmar tribunal, año, materia y etapa procesal.
- Extraer el holding real, no solo el resultado.
- Registrar por qué el caso sirve para litigio.

3. Ficha de curación
- Completar la ficha en `templates/curation_case_sheet.md`.
- Solo pasar a JSON cuando la ficha tenga holding, razonamiento y fuente verificables.

4. Carga estructurada
- Copiar `templates/curated_real_case.template.json`.
- Crear un archivo curado en `backend/data/jurisprudence/`.
- Completar todos los campos obligatorios.

5. Validación automática
- Ejecutar:

```powershell
python backend/scripts/validate_jurisprudence_corpus.py
```

- Si hay errores, el dataset no debe etiquetarse como `real`.

6. Revisión final
- Verificar redundancia.
- Confirmar que `strategic_value` explique utilidad litigiosa real.
- Confirmar que `metadata.verification_status=verified` y `metadata.curation_status=approved`.

## Criterios de inclusión

- Fuente verificable.
- Holding claro.
- Issue jurídico útil para recuperación.
- Hechos relevantes suficientes para analogía.
- Utilidad estratégica concreta para litigio.

## Criterios de exclusión

- Fallo redundante sin aporte diferencial.
- Resumen pobre o meramente administrativo.
- Caso sin holding claro.
- Fuente no verificable o inestable.
- Carga con placeholders o campos semivacíos.

## Campos obligatorios para `dataset_kind=real`

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

Metadata obligatoria:
- `verification_status=verified`
- `curation_status=approved`
- `verified_at`
- `verified_by`
- `curated_by`
- `source_reference`

## Plan por etapas

### Etapa 1: corpus mínimo curado
- 10 a 20 casos reales de alto valor práctico.
- Prioridad: divorcio, alimentos, sucesiones.
- Mezcla controlada entre tribunales nacionales y provinciales verificables.

### Etapa 2: enriquecimiento doctrinal y procesal
- Agregar `strategic_value` más fino.
- Etiquetas por tipo de conflicto, estándar probatorio y etapa procesal.
- Deduplicación por grupos argumentales.

### Etapa 3: subcorpus diferencial Jujuy
- Separar Jujuy como línea editorial propia.
- Cobertura de familia, alimentos y sucesiones con foco local.
- Añadir campos auxiliares en metadata para sesgo territorial, uso forense y frecuencia práctica.
- Exigir checklist local y deduplicación por `redundancy_group`.
