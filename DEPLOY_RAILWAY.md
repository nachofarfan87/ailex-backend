# Deploy en Railway

## Variables requeridas

- `ENV=production`
- `DEBUG=false`
- `SECRET_KEY=<valor-seguro>`
- `RAG_STORE_BACKEND=postgres`
- `DATABASE_URL=<PostgreSQL de Railway>`
- `PORT` lo inyecta Railway automaticamente

## Variables opcionales

- `FRONTEND_URL=https://ailex.com.ar`
- `CORS_ORIGINS=https://ailex.com.ar,https://www.ailex.com.ar`
- `CORS_ORIGIN_REGEX` solo para desarrollo local; no usar en produccion

## Start command

Railway puede usar el `Procfile` incluido:

```bash
bash start.sh
```

El script hace:

1. `alembic upgrade head`
2. `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`

## Base de datos

Railway debe tener un servicio PostgreSQL adjunto al backend.

- usar `RAG_STORE_BACKEND=postgres`
- apuntar `DATABASE_URL` al PostgreSQL entregado por Railway

Si Railway entrega una URL con prefijo `postgres://`, el backend la normaliza automaticamente a `postgresql://`.

## CORS en produccion

En `ENV=production` el backend permite por defecto:

- `https://ailex.com.ar`
- `https://www.ailex.com.ar`

Se pueden sumar origenes extra con `FRONTEND_URL` o `CORS_ORIGINS`.

## Verificacion post deploy

1. desplegar el servicio con PostgreSQL adjunto
2. abrir:

```text
https://<tu-servicio>.up.railway.app/health
```

3. verificar:

- `status = ok`
- `env = production`
- `database.is_postgres = true`
