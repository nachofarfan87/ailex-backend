"""
AILEX -- Endpoints de autenticacion.

POST /api/auth/register  -- registrar nuevo usuario
POST /api/auth/login     -- iniciar sesion, obtiene JWT
GET  /api/auth/me        -- datos del usuario autenticado
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.security import create_access_token, hash_password, verify_password
from app.db.database import get_db
from app.db.user_models import User

router = APIRouter(prefix="/api/auth", tags=["Autenticacion"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email:    EmailStr
    password: str       = Field(..., min_length=8, description="Minimo 8 caracteres")
    nombre:   str       = Field(..., min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class UserOut(BaseModel):
    id:         str
    email:      str
    nombre:     str
    is_active:  bool
    created_at: str | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         UserOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        nombre=user.nombre,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


def _make_token_response(user: User) -> TokenResponse:
    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token, user=_user_to_out(user))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Crea una cuenta nueva y devuelve un JWT listo para usar.

    El email debe ser unico en el sistema.
    """
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta con ese email.",
        )

    user = User(
        email=payload.email,
        nombre=payload.nombre.strip(),
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _make_token_response(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Iniciar sesion",
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Verifica credenciales y devuelve un JWT.

    El token tiene validez de 7 dias por defecto (configurable en Settings).
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contrasena incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta esta desactivada.",
        )
    return _make_token_response(user)


@router.get(
    "/me",
    response_model=UserOut,
    summary="Datos del usuario autenticado",
)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Devuelve el perfil del usuario que posee el JWT enviado."""
    return _user_to_out(current_user)
