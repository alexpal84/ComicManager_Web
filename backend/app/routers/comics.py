from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from ..database import get_db
from ..auth import require_auth
from ..models import Comic
from ..schemas import ComicOut, ComicUpdate, BulkEditRequest, BulkComicInfoRequest, MoveRequest, RenamePatternRequest
from ..mover import move_comic, render_pattern
from .. import archive_utils
from ..tasks import submit, get, active

router = APIRouter(prefix="/api/comics", tags=["comics"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[ComicOut])
def list_comics(
    db: Session = Depends(get_db),
    library_id: Optional[int] = None,
    q: Optional[str] = Query(None, description="Búsqueda libre en serie/título/editorial"),
    publisher: Optional[str] = None,
    genre: Optional[str] = None,
    unread_only: bool = False,
    missing: Optional[str] = Query(None, description="Campos vacíos separados por coma"),
    missing_mode: str = Query("any", pattern="^(any|all)$"),
    format: Optional[str] = None,
    metadata_dirty: Optional[bool] = None,
    comicinfo_written: Optional[bool] = None,
    sort: str = Query("series", pattern="^(series|number|title|publisher|year|added_at|updated_at|filename|page_count|file_size|rating)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    query = db.query(Comic)
    if library_id:
        query = query.filter(Comic.library_id == library_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Comic.series.ilike(like), Comic.title.ilike(like), Comic.publisher.ilike(like)))
    if publisher:
        query = query.filter(Comic.publisher == publisher)
    if genre:
        query = query.filter(Comic.genre.ilike(f"%{genre}%"))
    if unread_only:
        query = query.filter(Comic.read == False)  # noqa: E712
    if format:
        query = query.filter(Comic.format == format.lower())
    if metadata_dirty is not None:
        query = query.filter(Comic.metadata_dirty == metadata_dirty)
    if comicinfo_written is not None:
        query = query.filter(Comic.comicinfo_written == comicinfo_written)
    missing_fields = {
        "series": Comic.series, "number": Comic.number, "title": Comic.title,
        "year": Comic.year, "publisher": Comic.publisher, "writer": Comic.writer,
        "penciller": Comic.penciller, "genre": Comic.genre, "summary": Comic.summary, "tags": Comic.tags,
        "language": Comic.language, "cover": Comic.cover_thumbnail,
        "comicinfo": Comic.comicinfo_synced_at,
    }
    missing_conditions = []
    for field in filter(None, (missing or "").split(",")):
        column = missing_fields.get(field)
        if column is None:
            raise HTTPException(400, f"Filtro de metadato no válido: {field}")
        if field in {"year", "cover", "comicinfo"}:
            missing_conditions.append(column.is_(None))
        else:
            missing_conditions.append(or_(column.is_(None), column == ""))
    if missing_conditions:
        query = query.filter(and_(*missing_conditions) if missing_mode == "all" else or_(*missing_conditions))

    sort_col = getattr(Comic, sort)
    direction = sort_col.desc() if order == "desc" else sort_col.asc()
    query = query.order_by(direction, Comic.id.asc())
    return query.offset(offset).limit(limit).all()


@router.get("/{comic_id:int}", response_model=ComicOut)
def get_comic(comic_id: int, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    return comic


def _apply_changes(comic: Comic, changes: ComicUpdate):
    data = changes.model_dump(exclude={"write_comicinfo"}, exclude_unset=True)
    for field, value in data.items():
        setattr(comic, field, value)
    metadata_fields = set(data) - {"read", "last_page_read", "rating"}
    if metadata_fields:
        comic.metadata_dirty = True
        comic.comicinfo_written = False


@router.put("/{comic_id:int}", response_model=ComicOut)
def update_comic(comic_id: int, changes: ComicUpdate, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")

    _apply_changes(comic, changes)
    db.commit()
    db.refresh(comic)

    if changes.write_comicinfo:
        if comic.format != "cbz":
            raise HTTPException(400, "Solo se puede escribir ComicInfo.xml en archivos .cbz. Convierte el .cbr primero.")
        def write(c, session):
            from ..backup import backup_file
            import datetime as dt
            backup_file(c.path, tag="before_comicinfo_write")
            archive_utils.write_comicinfo_into_cbz(c.path, c)
            c.comicinfo_synced_at = dt.datetime.utcnow()
            c.comicinfo_written = True
            c.metadata_dirty = False
            session.commit()
        task_id = submit("writing_comicinfo", [comic.id], write)
        db.refresh(comic)
        return {**ComicOut.model_validate(comic).model_dump(), "task_id": task_id}

    return comic


@router.post("/bulk-edit")
def bulk_edit(payload: BulkEditRequest, db: Session = Depends(get_db)):
    comics = db.query(Comic).filter(Comic.id.in_(payload.comic_ids)).all()
    if not comics:
        raise HTTPException(404, "No se encontraron cómics con esos IDs")

    updated_ids = []
    comicinfo_errors = []
    for comic in comics:
        _apply_changes(comic, payload.changes)
        updated_ids.append(comic.id)

    db.commit()

    if payload.changes.write_comicinfo:
        from ..backup import backup_file
        import datetime as dt
        for comic in comics:
            if comic.format != "cbz":
                comicinfo_errors.append(f"{comic.filename}: es .{comic.format}, conviértelo a cbz primero")
                continue
            try:
                backup_file(comic.path, tag="before_bulk_comicinfo_write")
                archive_utils.write_comicinfo_into_cbz(comic.path, comic)
                comic.comicinfo_synced_at = dt.datetime.utcnow()
                comic.comicinfo_written = True
                comic.metadata_dirty = False
            except Exception as e:
                comicinfo_errors.append(f"{comic.filename}: {e}")
        db.commit()

    return {"updated": len(updated_ids), "comic_ids": updated_ids, "comicinfo_errors": comicinfo_errors}


@router.post("/bulk-write-comicinfo")
def bulk_write_comicinfo(payload: BulkComicInfoRequest, db: Session = Depends(get_db)):
    def write(comic, session):
        from ..backup import backup_file
        import datetime as dt
        if comic.format != "cbz": raise ValueError("no es CBZ")
        backup_file(comic.path, tag="before_bulk_comicinfo_write")
        archive_utils.write_comicinfo_into_cbz(comic.path, comic)
        comic.comicinfo_synced_at = dt.datetime.utcnow()
        comic.comicinfo_written = True
        comic.metadata_dirty = False
        session.commit()
        return {"filename": comic.filename}
    task_id = submit("writing_comicinfo", payload.comic_ids, write)
    return {"accepted": True, "task_id": task_id, "total": len(payload.comic_ids)}

@router.get("/tasks")
def list_tasks():
    return {"tasks": active()}

@router.get("/tasks/{task_id}")
def task_status(task_id: str):
    task = get(task_id)
    if not task: raise HTTPException(404, "Tarea no encontrada")
    return task


@router.post("/move")
def move(payload: MoveRequest, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(payload.comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    try:
        new_path = move_comic(db, comic, payload.new_relative_path)
    except (FileExistsError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"new_path": new_path}


@router.post("/rename-preview")
def rename_preview(payload: RenamePatternRequest, db: Session = Depends(get_db)):
    comics = db.query(Comic).filter(Comic.id.in_(payload.comic_ids)).all()
    preview = [{"comic_id": c.id, "current": c.path, "new_relative": render_pattern(c, payload.pattern)} for c in comics]
    return {"preview": preview}


@router.post("/rename-apply")
def rename_apply(payload: RenamePatternRequest, db: Session = Depends(get_db)):
    if payload.dry_run:
        raise HTTPException(400, "dry_run=True: usa /rename-preview para previsualizar, o pon dry_run=false para aplicar")
    comics = db.query(Comic).filter(Comic.id.in_(payload.comic_ids)).all()
    results = []
    for c in comics:
        try:
            new_rel = render_pattern(c, payload.pattern)
            new_path = move_comic(db, c, new_rel)
            results.append({"comic_id": c.id, "ok": True, "new_path": new_path})
        except Exception as e:
            results.append({"comic_id": c.id, "ok": False, "error": str(e)})
    return {"results": results}


@router.delete("/{comic_id:int}")
def remove_from_index(comic_id: int, db: Session = Depends(get_db)):
    """Elimina el cómic solo del índice de esta app. Nunca borra el fichero físico."""
    comic = db.query(Comic).get(comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    db.delete(comic)
    db.commit()
    return {"ok": True}
