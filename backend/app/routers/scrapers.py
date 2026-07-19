import datetime as dt
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_auth
from ..models import Comic
from ..schemas import ScraperSearchRequest, ScraperApplyRequest, ScraperBulkApplyRequest
from ..scrapers import get_scraper
from ..scrapers.comicvine import ComicVineNotConfigured
from ..scrapers.whakoom import WhakoomAuthenticationError
from .. import archive_utils
from ..backup import backup_file

router = APIRouter(prefix="/api/scrapers", tags=["scrapers"], dependencies=[Depends(require_auth)])


def _normalise_number(value):
    value = str(value or "").strip().lower().replace("#", "")
    numeric = re.search(r"\d+(?:[.,]\d+)?", value)
    if numeric:
        value = numeric.group(0)
    try:
        number = float(value.replace(",", "."))
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError:
        return value


def _apply_details(comic, details):
    cover_url = details.pop("cover_url", None)
    source_url = details.get("source_url")
    for field, value in details.items():
        if value not in (None, "") and hasattr(comic, field):
            setattr(comic, field, value)
    if source_url:
        note = f"Fuente scraper: {source_url}"
        existing_notes = (comic.notes or "").strip()
        if source_url not in existing_notes:
            comic.notes = f"{existing_notes}\n{note}".strip() if existing_notes else note
    comic.metadata_dirty = True
    comic.comicinfo_written = False
    return cover_url


@router.post("/search")
def search(payload: ScraperSearchRequest):
    scraper = get_scraper(payload.scraper)
    try:
        return {"results": scraper.search(payload.query)}
    except ComicVineNotConfigured as e:
        raise HTTPException(400, str(e))
    except WhakoomAuthenticationError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.get("/whakoom/series-issues")
def whakoom_series_issues(series_url: str):
    scraper = get_scraper("whakoom")
    return {"issues": scraper.get_series_issues(series_url)}


@router.get("/comicvine/volume-issues")
def comicvine_volume_issues(volume_ref: str):
    volume_id = volume_ref.split(":", 1)[1] if ":" in volume_ref else volume_ref
    scraper = get_scraper("comicvine")
    try:
        return {"issues": scraper.get_volume_issues(volume_id)}
    except ComicVineNotConfigured as e:
        raise HTTPException(400, str(e))


@router.post("/apply")
def apply(payload: ScraperApplyRequest, db: Session = Depends(get_db)):
    comic = db.query(Comic).get(payload.comic_id)
    if not comic:
        raise HTTPException(404, "Cómic no encontrado")

    scraper = get_scraper(payload.scraper)
    try:
        details = scraper.get_details(payload.ref)
    except ComicVineNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Error obteniendo datos del scraper: {e}")

    cover_url = _apply_details(comic, details)

    if cover_url:
        try:
            import requests
            resp = requests.get(cover_url, timeout=20)
            resp.raise_for_status()
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img.thumbnail((480, 960))
            out_path = comic.cover_thumbnail or f"{comic.id}.jpg"
            from ..config import COVERS_DIR
            img.save(COVERS_DIR / out_path, "JPEG", quality=85)
            comic.cover_thumbnail = out_path
        except Exception:
            pass  # si falla la portada remota, no bloqueamos el resto de metadatos

    db.commit()
    db.refresh(comic)

    if payload.write_comicinfo:
        if comic.format != "cbz":
            raise HTTPException(400, "Solo se puede escribir ComicInfo.xml en archivos .cbz. Convierte el .cbr primero.")
        backup_file(comic.path, tag="before_scraper_comicinfo_write")
        archive_utils.write_comicinfo_into_cbz(comic.path, comic)
        comic.comicinfo_synced_at = dt.datetime.utcnow()
        comic.comicinfo_written = True
        comic.metadata_dirty = False
        db.commit()
        db.refresh(comic)

    return comic


@router.post("/bulk-apply")
def bulk_apply(payload: ScraperBulkApplyRequest, db: Session = Depends(get_db)):
    comics = db.query(Comic).filter(Comic.id.in_(payload.comic_ids)).all()
    if not comics:
        raise HTTPException(404, "No se encontraron cómics con esos IDs")
    scraper = get_scraper(payload.scraper)
    try:
        if payload.scraper == "whakoom":
            issues = scraper.get_series_issues(payload.series_ref)
        else:
            volume_id = payload.series_ref.split(":", 1)[-1]
            issues = scraper.get_volume_issues(volume_id)
    except Exception as e:
        raise HTTPException(502, f"Error obteniendo los números de la serie: {e}")

    issue_by_number = {_normalise_number(i.get("number")): i for i in issues}
    matches, unmatched = [], []
    for comic in comics:
        issue = issue_by_number.get(_normalise_number(comic.number))
        if issue:
            matches.append({"comic": comic, "issue": issue})
        else:
            unmatched.append({"comic_id": comic.id, "filename": comic.filename, "number": comic.number})

    preview = [{
        "comic_id": item["comic"].id,
        "filename": item["comic"].filename,
        "comic_number": item["comic"].number,
        "issue_number": item["issue"].get("number"),
        "issue_title": item["issue"].get("title", ""),
        "issue_ref": item["issue"].get("url") or item["issue"].get("ref"),
    } for item in matches]
    if payload.dry_run:
        return {"matched": len(matches), "unmatched": unmatched, "preview": preview, "updated": 0, "errors": []}

    updated, errors = [], []
    for item in matches:
        comic, issue = item["comic"], item["issue"]
        ref = issue.get("url") or issue.get("ref")
        try:
            details = scraper.get_details(ref)
            _apply_details(comic, details)
            comic.source_scraper = payload.scraper
            comic.source_url = ref
            db.commit()
            if payload.write_comicinfo:
                if comic.format != "cbz":
                    raise ValueError("no es CBZ; metadatos guardados solo en la base de datos")
                backup_file(comic.path, tag="before_bulk_scraper_comicinfo_write")
                archive_utils.write_comicinfo_into_cbz(comic.path, comic)
                comic.comicinfo_synced_at = dt.datetime.utcnow()
                comic.comicinfo_written = True
                comic.metadata_dirty = False
                db.commit()
            updated.append(comic.id)
        except Exception as e:
            db.rollback()
            errors.append({"comic_id": comic.id, "filename": comic.filename, "error": str(e)})
    return {"matched": len(matches), "unmatched": unmatched, "preview": preview, "updated": len(updated), "updated_ids": updated, "errors": errors}
