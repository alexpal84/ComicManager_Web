import datetime as dt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_auth
from ..models import Comic
from ..schemas import ConvertRequest, BulkConvertRequest
from .. import archive_utils
from ..backup import backup_file
from ..config import DELETE_ORIGINAL_AFTER_CONVERT

router = APIRouter(prefix="/api/convert", tags=["convert"], dependencies=[Depends(require_auth)])


def _convert_comic(comic, delete_original: bool, db: Session):
    if comic.format not in ("cbr", "rar"):
        raise ValueError(f"El cómic ya es .{comic.format}, no hace falta convertirlo")
    backup_file(comic.path, tag="before_cbr2cbz")
    new_path = archive_utils.convert_cbr_to_cbz(comic.path, delete_original=delete_original)
    comic.path = new_path
    comic.filename = new_path.split("/")[-1]
    comic.format = "cbz"
    comic.updated_at = dt.datetime.utcnow()
    db.commit()
    return new_path


@router.post("")
def convert(payload: ConvertRequest, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(payload.comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    delete_original = payload.delete_original if payload.delete_original is not None else DELETE_ORIGINAL_AFTER_CONVERT
    try:
        new_path = _convert_comic(comic, delete_original, db)
    except (FileExistsError, RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))
    db.refresh(comic)

    return {
        "ok": True,
        "new_path": new_path,
        "original_kept": not delete_original,
        "note": "El .cbr original se ha conservado junto al nuevo .cbz." if not delete_original
                else "El .cbr original se ha eliminado tras verificar el número de páginas.",
    }


@router.post("/bulk")
def convert_bulk(payload: BulkConvertRequest, db: Session = Depends(get_db)):
    comics = db.query(Comic).filter(Comic.id.in_(payload.comic_ids)).all()
    results = []
    for comic in comics:
        try:
            new_path = _convert_comic(comic, payload.delete_original, db)
            results.append({"comic_id": comic.id, "ok": True, "new_path": new_path})
        except Exception as e:
            db.rollback()
            results.append({"comic_id": comic.id, "ok": False, "filename": comic.filename, "error": str(e)})
    converted = sum(1 for result in results if result["ok"])
    return {"converted": converted, "failed": len(results) - converted, "results": results}
