from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_auth
from ..models import Comic
from .. import archive_utils
from ..config import COVERS_DIR

router = APIRouter(prefix="/api/reader", tags=["reader"], dependencies=[Depends(require_auth)])


@router.get("/{comic_id}/cover")
def get_cover(comic_id: int, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    if comic.cover_thumbnail:
        path = COVERS_DIR / comic.cover_thumbnail
        if path.exists():
            return FileResponse(path, media_type="image/jpeg")
    raise HTTPException(404, "Sin portada generada todavía")


@router.get("/{comic_id}/pages")
def get_page_count(comic_id: int, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    return {"page_count": comic.page_count}


@router.get("/{comic_id}/page/{page_index}")
def get_page(comic_id: int, page_index: int, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")
    try:
        data, mime = archive_utils.read_page_bytes(comic.path, page_index)
    except IndexError:
        raise HTTPException(404, "Página fuera de rango")
    except Exception as e:
        raise HTTPException(500, f"Error leyendo la página: {e}")
    return Response(content=data, media_type=mime)
