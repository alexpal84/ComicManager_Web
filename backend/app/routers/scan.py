import threading
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..auth import require_auth
from ..models import Library
from ..scanner import scan_library

router = APIRouter(prefix="/api/scan", tags=["scan"], dependencies=[Depends(require_auth)])

# Estado de escaneos en curso, en memoria (proceso único, uso personal)
_SCAN_STATUS: dict[int, dict] = {}
_LOCK = threading.Lock()


def _run_scan(library_id: int):
    db = SessionLocal()
    try:
        lib = db.query(Library).get(library_id)
        if not lib:
            return

        def progress_cb(stats):
            with _LOCK:
                _SCAN_STATUS[library_id] = {**stats, "running": True}

        stats = scan_library(db, lib, progress_cb=progress_cb)
        with _LOCK:
            _SCAN_STATUS[library_id] = {**stats, "running": False, "finished": True}
    except Exception as e:
        with _LOCK:
            _SCAN_STATUS[library_id] = {"running": False, "finished": True, "error": str(e)}
    finally:
        db.close()


@router.post("/{library_id}")
def start_scan(library_id: int, db: Session = Depends(get_db)):
    lib = db.query(Library).get(library_id)
    if not lib:
        raise HTTPException(404, "Biblioteca no encontrada")
    with _LOCK:
        if _SCAN_STATUS.get(library_id, {}).get("running"):
            raise HTTPException(409, "Ya hay un escaneo en curso para esta biblioteca")
        _SCAN_STATUS[library_id] = {"running": True, "found": 0, "added": 0, "updated": 0, "unchanged": 0}
    thread = threading.Thread(target=_run_scan, args=(library_id,), daemon=True)
    thread.start()
    return {"started": True}


@router.get("/{library_id}/status")
def scan_status(library_id: int):
    with _LOCK:
        return _SCAN_STATUS.get(library_id, {"running": False, "finished": False})
