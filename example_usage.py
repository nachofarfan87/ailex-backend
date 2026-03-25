# example_usage.py
#
# Ejemplo de uso del pipeline AILEX desde un script Python.
# Ejecutar desde backend/:
#   python example_usage.py

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from legal_engine import AilexPipeline

pipeline = AilexPipeline()

result = pipeline.run(
    query="plazo para contestar demanda",
    jurisdiction="jujuy",
    forum="civil",
    top_k=5,
    document_mode="formal",
    facts={
        "fecha_notificacion": "2026-03-10",
        "tipo_proceso": "ordinario",
    },
)

# Serializar resultado completo
data = result.to_dict()
print(json.dumps(data, ensure_ascii=False, indent=2))

# Documento generado (solo si document_mode fue solicitado)
if result.generated_document:
    print("\n--- DOCUMENTO GENERADO ---\n")
    print(result.generated_document)
else:
    print("\n[Sin documento generado: especificar document_mode]")
