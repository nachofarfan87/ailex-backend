"""
AILEX -- Dependencias FastAPI para autenticacion.

get_current_user   -- requiere token valido; lanza HTTP 401 si falla
get_optional_user  -- devuelve el usuario si hay token valido, None si no hay
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.database import get_db
from app.db.user_models import User

# HTTPBearer extrae el token del header Authorization: Bearer <token>
# auto_error=False hace que devuelva None en lugar de lanzar 403
# cuando el header no esta presente (necesario para get_optional_user)
_bearer_optional = HTTPBearer(auto_error=False)
_bearer_required  = HTTPBearer(auto_error=True)


def _resolve_user(
    token_str: str | None,
    db: Session,
    raise_on_missing: bool,
) -> Optional[User]:
    if token_str is None:
        if raise_on_missing:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de autenticacion requerido.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None

    payload = decode_access_token(token_str)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin identificador de usuario.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o desactivado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_required),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependencia que exige autenticacion.

    Uso:
        @router.get("/ruta")
        def ruta(user: User = Depends(get_current_user)):
            ...

    Lanza HTTP 401 si no hay token o si es invalido/expirado.
    """
    return _resolve_user(credentials.credentials, db, raise_on_missing=True)


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_optional),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Dependencia que acepta rutas anonimas y autenticadas.

    Uso:
        @router.get("/ruta")
        def ruta(user: Optional[User] = Depends(get_optional_user)):
            if user:
                ...  # autenticado
            else:
                ...  # anonimo

    Devuelve None si no hay header Authorization.
    Lanza HTTP 401 si hay token pero es invalido.
    """
    token_str = credentials.credentials if credentials else None
    return _resolve_user(token_str, db, raise_on_missing=False)
