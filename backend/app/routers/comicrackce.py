import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_auth
from ..comicrackce import importer

router = APIRouter(prefix="/api/comicrackce", tags=["comicrackce"], dependencies=[Depends(require_auth)])


@router.get("/inspect")
def inspect(xml_path: str):
    """
    Diagnóstico de la estructura real de tu ComicDb.xml, sin modificar nada.
    Súbelo primero al servidor (p.ej. dentro de la carpeta /data montada) y
    pasa aquí su ruta dentro del contenedor.
    """
    if not os.path.isfile(xml_path):
        raise HTTPException(404, f"No se encuentra el fichero: {xml_path}")
    return importer.inspect_structure(xml_path)


@router.get("/dry-run")
def dry_run(xml_path: str, db: Session = Depends(get_db)):
    """Informe de qué importaría, SIN tocar nuestra base de datos."""
    if not os.path.isfile(xml_path):
        raise HTTPException(404, f"No se encuentra el fichero: {xml_path}")
    return importer.dry_run_import(db, xml_path)


@router.post("/import")
def apply_import(xml_path: str, match_by: str = "path", db: Session = Depends(get_db)):
    """
    Aplica la importación sobre NUESTRA base de datos (nunca modifica el
    ComicDb.xml original). Solo rellena campos vacíos, no pisa nada que ya
    hayas editado desde esta app. match_by: "path" o "filename".
    """
    if not os.path.isfile(xml_path):
        raise HTTPException(404, f"No se encuentra el fichero: {xml_path}")
    if match_by not in ("path", "filename"):
        raise HTTPException(400, "match_by debe ser 'path' o 'filename'")
    return importer.apply_import(db, xml_path, match_by=match_by)
