# AILEX Backend

Backend de AILEX, una API FastAPI para asistencia juridica, aprendizaje adaptativo y despliegue beta controlado.

## Stack principal

- Python
- FastAPI
- SQLAlchemy
- Alembic
- Uvicorn
- PostgreSQL o SQLite segun entorno

## Correr local

Desde `backend/`:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

En Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Variables importantes

- `ENV`
- `DEBUG`
- `SECRET_KEY`
- `RAG_STORE_BACKEND`
- `DATABASE_URL`
- `PORT`
- `FRONTEND_URL`
- `CORS_ORIGINS`

## Deploy en Railway

- usar PostgreSQL adjunto
- configurar `ENV=production`
- configurar `RAG_STORE_BACKEND=postgres`
- configurar `DATABASE_URL`
- Railway ejecuta `bash start.sh` via `Procfile`

Mas detalle en [DEPLOY_RAILWAY.md](./DEPLOY_RAILWAY.md).

## Healthcheck

Endpoint:

```text
/health
```

Debe responder con estado, version, entorno y datos sanitizados de base de datos.
