import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..automation import _whakoom_call, _write_xml, allowed_incoming_path, detect_once, enqueue, has_minimum_metadata, settings
from ..database import get_db
from ..auth import require_auth
from ..models import IncomingComic
from ..mover import move_comic, render_pattern
from ..routers.scrapers import _apply_details
from ..scrapers import get_scraper
from .. import archive_utils

router = APIRouter(prefix="/api/automation", tags=["automation"], dependencies=[Depends(require_auth)])

_SETTING_FIELDS = {"enabled", "incoming_path", "target_library_id", "accept_suggestions", "convert", "scrape", "write_comicinfo", "move", "move_only_safe", "use_ai", "destination_pattern"}

def _out(item):
    return {"id": item.id, "source_path": item.source_path, "source_filename": item.source_filename,
            "comic_id": item.comic_id, "status": item.status, "last_step": item.last_step, "error": item.error,
            "candidates": json.loads(item.candidates_json or "[]"), "selected_candidate": json.loads(item.selected_candidate_json or "null"),
            "selected_manually": item.selected_manually, "planned_destination": item.planned_destination,
            "created_at": item.created_at, "updated_at": item.updated_at,
            "comic": {"series": item.comic.series, "number": item.comic.number, "title": item.comic.title, "cover": item.comic.cover_thumbnail} if item.comic else None}

@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    row = settings(db)
    return {key: getattr(row, key) for key in _SETTING_FIELDS}

@router.put("/settings")
def update_settings(payload: dict, db: Session = Depends(get_db)):
    row = settings(db)
    for key, value in payload.items():
        if key not in _SETTING_FIELDS: continue
        if key == "incoming_path": value = allowed_incoming_path(str(value))
        setattr(row, key, value)
    db.commit()
    return get_settings(db)

@router.get("/items")
def list_items(status: str = "", db: Session = Depends(get_db)):
    query = db.query(IncomingComic)
    if status and status != "all":
        groups = {"pending": ["Nuevo", "Esperando", "Procesando", "Valores propuestos", "Convirtiendo", "Buscando metadatos", "Listo para guardar", "Listo para mover"], "review": ["Necesita revisión"], "completed": ["Completado"], "errors": ["Error"]}
        query = query.filter(IncomingComic.status.in_(groups.get(status, [status])))
    return [_out(item) for item in query.order_by(IncomingComic.updated_at.desc()).limit(300).all()]


@router.post("/reconcile-ready")
def reconcile_ready_items(db: Session = Depends(get_db)):
    """Recover embedded metadata, then release review rows that are complete."""
    released = 0
    for item in db.query(IncomingComic).filter(IncomingComic.status == "Necesita revisión").all():
        if item.comic:
            try:
                embedded_metadata = archive_utils.read_comicinfo(item.comic.path)
            except Exception:
                embedded_metadata = None
            if embedded_metadata:
                for field, value in embedded_metadata.items():
                    if value not in (None, ""):
                        setattr(item.comic, field, value)
                item.comic.comicinfo_written = True
                item.comic.metadata_dirty = False
        if item.comic and has_minimum_metadata(item.comic):
            item.last_step = "metadatos"
            item.status = "Listo para mover" if item.comic.comicinfo_written else "Listo para guardar"
            item.error = None
            released += 1
    if released:
        db.commit()
    return {"released": released}

@router.post("/detect")
def detect():
    return {"ok": True, "detected": detect_once(force=True)}

@router.post("/process-pending")
def process_pending(db: Session = Depends(get_db)):
    ids = [row.id for row in db.query(IncomingComic).filter(IncomingComic.status.in_(["Nuevo", "Esperando", "Error"])).all()]
    for item_id in ids: enqueue(item_id, True)
    return {"started": len(ids)}

@router.post("/items/{item_id}/retry")
def retry(item_id: int, db: Session = Depends(get_db)):
    item = db.get(IncomingComic, item_id)
    if not item: raise HTTPException(404, "Elemento no encontrado")
    enqueue(item.id, True)
    return {"started": True}

@router.post("/items/{item_id}/skip")
def skip(item_id: int, db: Session = Depends(get_db)):
    item = db.get(IncomingComic, item_id)
    if not item: raise HTTPException(404, "Elemento no encontrado")
    item.status = "Omitido"; db.commit(); return {"ok": True}

@router.post("/items/{item_id}/candidate")
def select_candidate(item_id: int, payload: dict, db: Session = Depends(get_db)):
    item = db.get(IncomingComic, item_id)
    if not item or not item.comic: raise HTTPException(404, "Elemento o cómic no encontrado")
    candidate = next((c for c in json.loads(item.candidates_json or "[]") if c.get("id") == payload.get("id")), None)
    if not candidate: raise HTTPException(400, "Candidato no válido")
    try:
        scraper = get_scraper(candidate["source"])
        details = _whakoom_call(lambda: scraper.get_details(candidate["ref"])) if candidate["source"] == "whakoom" else scraper.get_details(candidate["ref"])
        _apply_details(item.comic, details, "fill_empty")
        item.comic.source_scraper, item.comic.source_url = candidate["source"], candidate["ref"]
        item.selected_candidate_json, item.selected_manually, item.last_step, item.status = json.dumps(candidate), True, "metadatos", "Listo para guardar"
        db.commit()
    except Exception as exc: raise HTTPException(502, f"No se pudo aplicar el candidato: {exc}")
    return _out(item)

@router.post("/items/{item_id}/write-comicinfo")
def write_item_comicinfo(item_id: int, db: Session = Depends(get_db)):
    item = db.get(IncomingComic, item_id)
    if not item or not item.comic or not (item.selected_candidate_json or has_minimum_metadata(item.comic)):
        raise HTTPException(400, "Completa Serie, Guionista y Etiquetas, o selecciona un candidato válido")
    try:
        _write_xml(item.comic); item.last_step, item.status = "xml", "Listo para mover"; db.commit()
    except Exception as exc: raise HTTPException(400, f"No se pudo escribir ComicInfo.xml: {exc}")
    return _out(item)

@router.post("/items/{item_id}/move")
def move_item(item_id: int, db: Session = Depends(get_db)):
    item, cfg = db.get(IncomingComic, item_id), settings(db)
    if not item or not item.comic or not (item.selected_candidate_json or has_minimum_metadata(item.comic)):
        raise HTTPException(400, "Completa Serie, Guionista y Etiquetas, o selecciona un candidato válido")
    try:
        destination = move_comic(db, item.comic, render_pattern(item.comic, cfg.destination_pattern))
        item.source_path, item.planned_destination, item.last_step, item.status = destination, destination, "movido", "Completado"; db.commit()
    except FileExistsError as exc:
        item.status, item.error = "Necesita revisión", str(exc); db.commit(); raise HTTPException(409, str(exc))
    except Exception as exc: raise HTTPException(400, f"No se pudo mover: {exc}")
    return _out(item)
