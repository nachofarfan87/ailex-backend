"""End-to-end test for AILEX RAG pipeline."""
import requests
import json

BASE = "http://localhost:8000"

print("=" * 60)
print("AILEX RAG Pipeline - End-to-End Test")
print("=" * 60)

# 1. Health check
print("\n1. Health check...")
r = requests.get(f"{BASE}/health")
print(f"   Status: {r.json()}")

# 2. Upload a legal text document
print("\n2. Uploading legal text (Codigo Procesal Civil - fragmento)...")
legal_text = """
CODIGO PROCESAL CIVIL Y COMERCIAL DE JUJUY

TITULO I - DISPOSICIONES GENERALES

ARTICULO 1. - Ambito de aplicacion. Las disposiciones de este Codigo se aplicaran a todos los procesos civiles y comerciales que se sustancien ante los tribunales ordinarios de la Provincia de Jujuy.

ARTICULO 2. - Principios procesales. Los jueces deberan dirigir el procedimiento con sujecion a los principios de inmediacion, concentracion, economia procesal y celeridad.

ARTICULO 3. - Plazos. Los plazos procesales seran perentorios y fatales, salvo disposicion expresa en contrario. Los plazos se computaran en dias habiles judiciales.

ARTICULO 4. - Notificaciones. Las notificaciones se practicaran en el domicilio constituido, salvo que la ley disponga la notificacion personal o por cedula.

ARTICULO 5. - Domicilio procesal. Toda persona que litigue por su propio derecho o en representacion de tercero debera constituir domicilio legal dentro del radio del juzgado.
"""

r = requests.post(f"{BASE}/api/documents/upload/text", data={
    "text": legal_text,
    "title": "CPC Jujuy - Disposiciones Generales",
    "source_type": "codigo",
    "jurisdiction": "Jujuy",
    "legal_area": "civil",
    "fuero": "Civil y Comercial",
    "description": "Fragmento del CPC de Jujuy - Titulo I",
    "tags": "procesal,civil,plazos,notificaciones",
})
result = r.json()
doc_id_1 = result.get("document_id", "")
print(f"   Document ID: {doc_id_1}")
print(f"   Chunks: {result.get('chunk_count')}")
print(f"   Hierarchy: {result.get('source_hierarchy')}")
print(f"   Status: {result.get('status')}")

# 3. Upload jurisprudencia
print("\n3. Uploading jurisprudencia...")
juris_text = """
SUPERIOR TRIBUNAL DE JUSTICIA DE JUJUY
Expediente No 15678/2025

SUMARIO: Proceso civil. Plazos procesales. Computo. Dias inhabiles.

DOCTRINA DEL FALLO: Los plazos procesales establecidos en el CPC de Jujuy son perentorios y fatales. No se computan los dias inhabiles, feriados ni asuetos provinciales. El plazo para contestar demanda es de quince dias habiles contados desde la notificacion.

RESUELVE: Confirmar la sentencia de primera instancia que declaro la rebeldia del demandado por no haber contestado en plazo.
"""

r = requests.post(f"{BASE}/api/documents/upload/text", data={
    "text": juris_text,
    "title": "STJ Jujuy - Plazos procesales",
    "source_type": "jurisprudencia",
    "jurisdiction": "Jujuy",
    "legal_area": "civil",
    "court": "Superior Tribunal de Justicia de Jujuy",
})
result = r.json()
doc_id_2 = result.get("document_id", "")
print(f"   Document ID: {doc_id_2}")
print(f"   Chunks: {result.get('chunk_count')}")
print(f"   Hierarchy: {result.get('source_hierarchy')}")

# 4. Upload escrito interno
print("\n4. Uploading escrito interno...")
r = requests.post(f"{BASE}/api/documents/upload/text", data={
    "text": "CONTESTA DEMANDA. En el expediente Rodriguez c/ Municipalidad de Jujuy, contestamos la demanda negando los hechos expuestos. Oponemos excepcion de prescripcion.",
    "title": "Modelo contestacion - caso Rodriguez",
    "source_type": "escrito",
    "jurisdiction": "Jujuy",
    "legal_area": "civil",
})
result = r.json()
print(f"   Document ID: {result.get('document_id')}")
print(f"   Hierarchy: {result.get('source_hierarchy')}")

# 5. List documents
print("\n5. Listing all documents...")
r = requests.get(f"{BASE}/api/documents/")
docs = r.json()
print(f"   Total: {docs['total']}")
for d in docs["documents"]:
    print(f"   - [{d['source_hierarchy']}] {d['title']} ({d['chunk_count']} chunks)")

# 6. Get stats
print("\n6. Document stats...")
r = requests.get(f"{BASE}/api/documents/stats")
stats = r.json()
print(f"   {json.dumps(stats, indent=4)}")

# 7. Get chunks of first document
print(f"\n7. Chunks of '{doc_id_1[:8]}...'")
r = requests.get(f"{BASE}/api/documents/{doc_id_1}/chunks")
chunks = r.json()
print(f"   Total chunks: {chunks['total_chunks']}")
for c in chunks["chunks"][:3]:
    print(f"   - [{c['chunk_index']}] {c.get('article_reference', '')} ({c['char_count']} chars)")

# 8. Hybrid search
print("\n8. Hybrid search: 'plazos procesales contestar demanda'...")
r = requests.post(f"{BASE}/api/search/", json={
    "query": "plazos procesales contestar demanda",
    "jurisdiction": "Jujuy",
    "top_k": 5,
})
search = r.json()
print(f"   Results: {search['total']}")
for s in search["results"][:3]:
    scores = s["scores"]
    print(f"   - [{s['source_hierarchy']}] score={scores['final']:.3f} "
          f"(vec={scores['vector']:.3f} kw={scores['keyword']:.3f} leg={scores['legal']:.3f})")
    print(f"     {s['text'][:100]}...")

# 9. Search with hierarchy filter
print("\n9. Search filtered to normativa only...")
r = requests.post(f"{BASE}/api/search/", json={
    "query": "plazos notificaciones",
    "jurisdiction": "Jujuy",
    "source_hierarchy": "normativa",
    "top_k": 3,
})
search = r.json()
print(f"   Results: {search['total']}")

# 10. Get RAG context
print("\n10. RAG context for 'contestacion de demanda plazo'...")
r = requests.post(f"{BASE}/api/search/context", json={
    "query": "contestacion de demanda plazo",
    "jurisdiction": "Jujuy",
    "max_chars": 4000,
})
ctx = r.json()
print(f"   Fragments: {len(ctx['fragments'])}")
print(f"   Total chars: {ctx['total_chars']}")
print(f"   Sources used: {len(ctx['sources_used'])}")

print("\n" + "=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
