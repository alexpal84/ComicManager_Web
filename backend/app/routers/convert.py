import datetime as dt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_auth
from ..models import Comic
from ..schemas import ConvertRequest
from .. import archive_utils
from ..backup import backup_file
from ..config import DELETE_ORIGINAL_AFTER_CONVERT

router = APIRouter(prefix="/api/convert", tags=["convert"], dependencies=[Depends(require_auth)])


@router.post("")
def convert(payload: ConvertRequest, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(payload.comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    if comic.format not in ("cbr", "rar"):
        raise HTTPException(400, f"El cómic ya es .{comic.format}, no hace falta convertirlo")

    delete_original = payload.delete_original if payload.delete_original is not None else DELETE_ORIGINAL_AFTER_CONVERT

    # Copia de seguridad del cbr original antes de tocar nada, siempre,
    # independientemente de si luego se borra o no.
    backup_file(comic.path, tag="before_cbr2cbz")

    try:
        new_path = archive_utils.convert_cbr_to_cbz(comic.path, delete_original=delete_original)
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))

    comic.path = new_path
    comic.filename = new_path.split("/")[-1]
    comic.format = "cbz"
    comic.updated_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(comic)

    return {
        "ok": True,
        "new_path": new_path,
        "original_kept": not delete_original,
        "note": "El .cbr original se ha conservado junto al nuevo .cbz." if not delete_original
                else "El .cbr original se ha eliminado tras verificar el número de páginas.",
    }
