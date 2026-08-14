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
from ..tasks import submit, get, active

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
    task_id = submit("converting", [comic.id], lambda c, session: {"new_path": _convert_comic(c, delete_original, session)})
    return {"accepted": True, "task_id": task_id}


@router.post("/bulk")
def convert_bulk(payload: BulkConvertRequest, db: Session = Depends(get_db)):
    task_id = submit("converting", payload.comic_ids,
                     lambda c, session: {"new_path": _convert_comic(c, payload.delete_original, session)})
    return {"accepted": True, "task_id": task_id, "total": len(payload.comic_ids)}

@router.get("/tasks")
def list_tasks():
    return {"tasks": active()}

@router.get("/tasks/{task_id}")
def task_status(task_id: str):
    task = get(task_id)
    if not task: raise HTTPException(404, "Tarea no encontrada")
    return task
