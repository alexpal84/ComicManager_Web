from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..auth import require_auth
from ..models import Library, Comic
from ..schemas import LibraryCreate, LibraryOut

router = APIRouter(prefix="/api/libraries", tags=["libraries"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[LibraryOut])
def list_libraries(db: Session = Depends(get_db)):
    libs = db.query(Library).all()
    out = []
    for lib in libs:
        count = db.query(func.count(Comic.id)).filter(Comic.library_id == lib.id).scalar()
        item = LibraryOut.model_validate(lib)
        item.comic_count = count or 0
        out.append(item)
    return out


@router.post("", response_model=LibraryOut)
def create_library(payload: LibraryCreate, db: Session = Depends(get_db)):
    import os
    if not os.path.isdir(payload.root_path):
        raise HTTPException(400, f"La ruta no existe o no es accesible dentro del contenedor: {payload.root_path}. "
                                  f"Recuerda montarla como volumen Docker.")
    existing = db.query(Library).filter(Library.root_path == payload.root_path).first()
    if existing:
        raise HTTPException(400, "Ya existe una biblioteca con esa ruta")
    lib = Library(name=payload.name, root_path=payload.root_path)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    out = LibraryOut.model_validate(lib)
    out.comic_count = 0
    return out


@router.delete("/{library_id}")
def delete_library(library_id: int, delete_from_disk: bool = False, db: Session = Depends(get_db)):
    lib = db.query(Library).get(library_id)
    if not lib:
        raise HTTPException(404, "Biblioteca no encontrada")
    if delete_from_disk:
        raise HTTPException(400, "Por seguridad, esta acción nunca borra ficheros físicos automáticamente.")
    db.delete(lib)  # solo borra el índice, nunca los ficheros
    db.commit()
    return {"ok": True}
