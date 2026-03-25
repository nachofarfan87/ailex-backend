# Plantillas Jurídicas — Jujuy

Este directorio contendrá las plantillas de escritos jurídicos
específicas para la jurisdicción de Jujuy.

## Estructura prevista

```
jujuy/
├── civil/
│   ├── demanda_ordinaria.md
│   ├── contestacion_demanda.md
│   ├── recurso_apelacion.md
│   └── ...
├── laboral/
│   ├── demanda_laboral.md
│   └── ...
├── penal/
│   └── ...
├── familia/
│   └── ...
└── contencioso/
    └── ...
```

## Formato de plantilla

Cada plantilla usa marcadores `{{NOMBRE_CAMPO}}` para datos que
el usuario debe completar. Las plantillas son versionables por 
archivo y se registran en la base de datos como `LegalTemplate`.

## Versionado

Las plantillas usan versionado semántico (1.0.0, 1.1.0, 2.0.0).
- Patch: correcciones menores de texto
- Minor: agregado de secciones opcionales
- Major: cambios en estructura o requisitos
