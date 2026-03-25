"""
Regresiones del flujo de carga al corpus.

Verifica que el material normativo se clasifique como normativa y que
preserve chunking por artículo cuando corresponde.
"""

from app.api.routes import documents


NORMATIVE_TEXT = """
CONSTITUCION NACIONAL

Articulo 1.- La Nacion Argentina adopta para su gobierno la forma representativa republicana federal.

Articulo 2.- El Gobierno federal sostiene el culto catolico apostolico romano.

Articulo 3.- Las autoridades que ejercen el Gobierno federal residen en la Ciudad de Buenos Aires.
""".strip()


INTERNAL_TEXT = """
Minuta interna para el equipo.

Revisar la documental pendiente, coordinar la estrategia de contestacion y preparar un resumen operativo para la audiencia.
""".strip()


async def test_normative_upload_uses_normativa_hierarchy_and_article_chunks(client):
    documents.store.clear()

    try:
        response = await client.post(
            "/api/documents/upload/text",
            data={
                "title": "Constitucion Nacional - prueba",
                "text": NORMATIVE_TEXT,
                "source_type": "codigo",
                "jurisdiction": "Nacional",
                "legal_area": "constitucional",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["source_type"] == "codigo"
        assert data["source_hierarchy"] == "normativa"
        assert data["chunk_count"] > 1

        chunks_response = await client.get(f"/api/documents/{data['document_id']}/chunks")
        assert chunks_response.status_code == 200

        chunk_payload = chunks_response.json()
        assert chunk_payload["total_chunks"] == data["chunk_count"]

        article_refs = [chunk["article_reference"] for chunk in chunk_payload["chunks"]]
        assert article_refs[:3] == ["Art. 1", "Art. 2", "Art. 3"]
    finally:
        documents.store.clear()


async def test_internal_upload_remains_internal(client):
    documents.store.clear()

    try:
        response = await client.post(
            "/api/documents/upload/text",
            data={
                "title": "Nota interna - prueba",
                "text": INTERNAL_TEXT,
                "source_type": "escrito",
                "jurisdiction": "Jujuy",
                "legal_area": "civil",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["source_type"] == "escrito"
        assert data["source_hierarchy"] == "interno"
        assert data["chunk_count"] >= 1
    finally:
        documents.store.clear()
