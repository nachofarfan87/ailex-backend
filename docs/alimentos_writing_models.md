# Modelos de Escritos de Alimentos

## Finalidad
Esta biblioteca reune ocho escritos reales de alimentos seleccionados como modelos de escritura y referencia forense para futuras mejoras de AILEX.

No son fuentes jurisprudenciales ni normativas.
No deben citarse como precedentes.
Su uso correcto es como insumo de estilo litigioso, estructura de pretension, orden argumental y estrategia de redaccion.

## Convencion de archivos
- Carpeta canonica: `backend/data/writing_models/alimentos/`
- Archivo indice: `backend/data/writing_models/alimentos/index.json`
- Convencion de nombres: `NNN_nombre_normalizado.pdf`
- Se conservan los PDFs originales con su nombre heredado para trazabilidad.
- Los nombres canonicos son los que deben usarse hacia adelante para referencias internas y futuras curaciones.

## Biblioteca seleccionada
### `001_belasquez.pdf`
- Calificacion: 5/5
- Tipo: alimentos estandar contra progenitor
- Aporta:
  - estructura base del escrito
  - conflicto claro
  - necesidades concretas del alimentado
  - componente habitacional como parte de los alimentos
  - prueba concreta y no abstracta

### `005_laura.pdf`
- Calificacion: 5/5
- Tipo: alimentos estandar con vulnerabilidad y violencia
- Aporta:
  - estructura base solida
  - contexto de violencia y vulnerabilidad
  - tono institucional de proteccion reforzada
  - integracion de hechos sensibles sin perder claridad litigiosa

### `006_martinez_hijo_mayor.pdf`
- Calificacion: 5/5
- Tipo: hijo mayor estudiante
- Aporta:
  - encuadre especifico de art. 663 CCyC
  - regularidad academica
  - continuidad de asistencia
  - diferenciacion frente a alimentos estandar

### `007_martinezz_mixto.pdf`
- Calificacion: 4/5
- Tipo: caso mixto hijos + conyuge
- Aporta:
  - separacion clara de rubros
  - orden de montos o componentes
  - estructura util para pretensiones mixtas

### `008_nuin_vulnerabilidad.pdf`
- Calificacion: 5/5
- Tipo: vulnerabilidad, bajos recursos y defensoria
- Aporta:
  - justicia gratuita
  - SMVM como parametro orientativo
  - ANSES, AUH y CBU como soportes operativos
  - tono institucional de proteccion reforzada

### `010_perez.pdf`
- Calificacion: 5/5
- Tipo: alimentos estandar con alta densidad argumental
- Aporta:
  - estructura base fuerte
  - justificacion procesal
  - apoyo en derechos humanos
  - medidas previas y planteo robusto

### `014_nieva_urgencia.pdf`
- Calificacion: 5/5
- Tipo: urgencia y medidas fuertes
- Aporta:
  - embargo
  - habilitacion de dia y hora
  - pase a feria
  - tono de urgencia real
- Uso prudente:
  - no debe replicarse automaticamente
  - solo corresponde cuando el caso aporta soporte factico para tutela urgente

### `015_ramirez_ascendientes.pdf`
- Calificacion: 5/5
- Tipo: alimentos contra ascendientes
- Aporta:
  - explicacion clara de subsidiariedad
  - insuficiencia o imposibilidad del obligado principal
  - eventual litisexpensas
  - base normativa mas cerrada

## Como reutilizar esta biblioteca en AILEX
- Usar `index.json` como fuente de metadata para futuras curaciones de prompts o perfiles de redaccion.
- Tratar estos PDFs como modelos de escritura y no como autoridad juridica.
- Reutilizar patrones solo cuando el `case_profile` o la estrategia del caso los justifiquen.
- Mantener separada esta biblioteca de cualquier corpus jurisprudencial o normativo.
- Si se incorporan nuevos modelos, asignar:
  - nombre canonico consistente
  - calificacion
  - categoria
  - `use_for`
  - nota breve de aporte diferencial

## Estado de cierre
- Biblioteca de alimentos identificada y normalizada
- Ocho modelos seleccionados con metadata estructurada
- Trazabilidad mantenida entre archivo original y archivo canonico
- Lista para futuras mejoras de redaccion sin tocar el motor juridico
