"""
AILEX -- Utilidades de seguridad para autenticacion JWT.

Funciones:
  hash_password(plain)            -- genera hash bcrypt de la contrasena
  verify_password(plain, hashed)  -- verifica contrasena contra hash
  create_access_token(data)       -- emite un JWT firmado con HS256
  decode_access_token(token)      -- decodifica y valida JWT; None si invalido

El algoritmo es HS256 (HMAC-SHA256).  La clave secreta se configura
en Settings.secret_key; en produccion debe ser un valor aleatorio de
al menos 256 bits (32 bytes hex).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Retorna el hash bcrypt de la contrasena en texto plano."""
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Retorna True si `plain` coincide con `hashed`."""
    return _pwd_ctx.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

_ALGORITHM = "HS256"


def create_access_token(
    data: dict[str, Any],
    expires_minutes: int | None = None,
) -> str:
    """
    Emite un JWT firmado.

    Args:
        data:            Payload a incluir (p.ej. {"sub": user_id}).
        expires_minutes: Tiempo de vida en minutos.  Si es None usa el
                         valor de Settings.access_token_expire_minutes.

    Returns:
        Token JWT como string.
    """
    expire_delta = timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )
    payload = dict(data)
    payload["exp"] = datetime.now(tz=timezone.utc) + expire_delta
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """
    Decodifica y valida un JWT.

    Returns:
        El payload como dict si el token es valido y no expiró,
        None en caso contrario.
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except JWTError:
        return None
