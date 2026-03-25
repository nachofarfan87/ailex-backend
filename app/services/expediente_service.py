"""
AILEX -- Servicio de expedientes.

Encapsula toda la logica de negocio para la gestion de expedientes.
Las rutas solo deben llamar a estas funciones; no deben acceder
directamente al ORM.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.user_models import Consulta, Expediente


def _normalize_text(value: Optional[str], default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _normalize_partes_json(value: Optional[str]) -> str:
    raw = _normalize_text(value, default="[]")
    if not raw:
        return "[]"

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El campo 'partes_json' debe ser JSON valido serializado en texto.",
        ) from exc

    if not isinstance(parsed, (list, dict)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El campo 'partes_json' debe representar un array o un objeto JSON.",
        )

    return json.dumps(parsed, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def get_expedientes(
    db: Session,
    user_id: str,
    estado: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Expediente]:
    """Lista los expedientes del usuario, filtrados opcionalmente por estado."""
    q = (
        db.query(Expediente)
        .filter(Expediente.user_id == user_id)
    )
    if estado:
        q = q.filter(Expediente.estado == estado)
    return (
        q.order_by(Expediente.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_expediente(
    db: Session,
    expediente_id: str,
    user_id: str,
) -> Expediente:
    """
    Obtiene un expediente por ID.

    Lanza HTTP 404 si no existe.
    Lanza HTTP 403 si pertenece a otro usuario.
    """
    exp = db.get(Expediente, expediente_id)
    if exp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expediente '{expediente_id}' no encontrado.",
        )
    if exp.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para acceder a este expediente.",
        )
    return exp


def get_consultas_by_expediente(
    db: Session,
    expediente_id: str,
    user_id: str,
    skip: int = 0,
    limit: int = 50,
) -> list[Consulta]:
    """Lista las consultas vinculadas a un expediente (verificando ownership)."""
    # Valida que el expediente pertenezca al usuario
    get_expediente(db, expediente_id, user_id)
    return (
        db.query(Consulta)
        .filter(Consulta.expediente_id == expediente_id)
        .order_by(Consulta.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def create_expediente(
    db: Session,
    user_id: str,
    titulo: str,
    caratula: str = "",
    numero: str = "",
    materia: str = "",
    juzgado: str = "",
    jurisdiccion: str = "jujuy",
    descripcion: str = "",
    notas_estrategia: str = "",
    tipo_caso: str = "",
    subtipo_caso: str = "",
    partes_json: str = "[]",
    hechos_relevantes: str = "",
    pretension_principal: str = "",
    estado_procesal: str = "",
    riesgos_clave: str = "",
    estrategia_base: str = "",
    proxima_accion_sugerida: str = "",
) -> Expediente:
    """Crea y persiste un nuevo expediente."""
    normalized_title = _normalize_text(titulo)
    if not normalized_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El titulo del expediente es obligatorio.",
        )

    exp = Expediente(
        user_id=user_id,
        titulo=normalized_title,
        caratula=_normalize_text(caratula),
        numero=_normalize_text(numero),
        materia=_normalize_text(materia),
        juzgado=_normalize_text(juzgado),
        jurisdiccion=_normalize_text(jurisdiccion, default="jujuy") or "jujuy",
        descripcion=_normalize_text(descripcion),
        notas_estrategia=_normalize_text(notas_estrategia),
        tipo_caso=_normalize_text(tipo_caso),
        subtipo_caso=_normalize_text(subtipo_caso),
        partes_json=_normalize_partes_json(partes_json),
        hechos_relevantes=_normalize_text(hechos_relevantes),
        pretension_principal=_normalize_text(pretension_principal),
        estado_procesal=_normalize_text(estado_procesal),
        riesgos_clave=_normalize_text(riesgos_clave),
        estrategia_base=_normalize_text(estrategia_base),
        proxima_accion_sugerida=_normalize_text(proxima_accion_sugerida),
        estado="activo",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def update_expediente(
    db: Session,
    expediente_id: str,
    user_id: str,
    **fields: str,
) -> Expediente:
    """
    Actualiza campos de un expediente.

    Solo se actualizan los campos presentes en `fields` y que sean
    atributos validos del modelo.  Ignora claves desconocidas.
    """
    exp = get_expediente(db, expediente_id, user_id)

    _allowed = {
        "titulo", "caratula", "numero", "materia",
        "juzgado", "jurisdiccion", "descripcion",
        "notas_estrategia", "estado", "tipo_caso",
        "subtipo_caso", "partes_json", "hechos_relevantes",
        "pretension_principal", "estado_procesal",
        "riesgos_clave", "estrategia_base",
        "proxima_accion_sugerida",
    }
    for key, value in fields.items():
        if key in _allowed and value is not None:
            if key == "partes_json":
                setattr(exp, key, _normalize_partes_json(value))
            elif key == "jurisdiccion":
                setattr(exp, key, _normalize_text(value, default="jujuy") or "jujuy")
            elif key == "titulo":
                normalized_title = _normalize_text(value)
                if not normalized_title:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="El titulo del expediente no puede quedar vacio.",
                    )
                setattr(exp, key, normalized_title)
            else:
                setattr(exp, key, _normalize_text(value))

    db.commit()
    db.refresh(exp)
    return exp


def archive_expediente(
    db: Session,
    expediente_id: str,
    user_id: str,
) -> Expediente:
    """Marca el expediente como archivado (soft-delete)."""
    return update_expediente(db, expediente_id, user_id, estado="archivado")
