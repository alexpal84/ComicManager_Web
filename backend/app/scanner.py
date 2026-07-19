from __future__ import annotations
import os
import re
import hashlib
import datetime as dt
from pathlib import Path
from typing import Iterator

from sqlalchemy.orm import Session

from .config import SUPPORTED_EXTENSIONS
from .models import Comic, Library
from . import archive_utils

# Intenta deducir "Serie" y "Numero" a partir del nombre de archivo cuando
# no hay ComicInfo.xml embebido. Cubre los patrones más comunes:
#   Serie Nombre 001 (2020).cbz
#   Serie Nombre #1.cbz
#   Serie Nombre v02 #003.cbz
FILENAME_PATTERNS = [
    re.compile(r"^(?P<series>.+?)\s*#(?P<number>\d+(?:\.\d+)?)\s*(?:\((?P<year>\d{4})\))?", re.IGNORECASE),
    re.compile(r"^(?P<series>.+?)\s+(?P<number>\d{2,4}(?:\.\d+)?)\s*(?:\((?P<year>\d{4})\))?$", re.IGNORECASE),
]


def guess_metadata_from_filename(filename: str) -> dict:
    stem = Path(filename).stem
    stem = re.sub(r"\s*\[[^\]]*\]", "", stem)  # quita tags tipo [Digital]
    for pattern in FILENAME_PATTERNS:
        m = pattern.match(stem)
        if m:
            gd = m.groupdict()
            return {
                "series": (gd.get("series") or "").strip(" -_"),
                "number": (gd.get("number") or "").strip(),
                "year": int(gd["year"]) if gd.get("year") else None,
            }
    return {"series": stem, "number": "", "year": None}


def _iter_comic_files(root: str) -> Iterator[str]:
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            if Path(fname).suffix.lower() in SUPPORTED_EXTENSIONS:
                yield os.path.join(dirpath, fname)


def _file_quick_hash(path: str) -> str:
    """Hash rápido (no del contenido completo, para no leer 15000 cbz enteros):
    basado en tamaño + mtime + primeros bytes."""
    st = os.stat(path)
    h = hashlib.sha1()
    h.update(str(st.st_size).encode())
    h.update(str(st.st_mtime).encode())
    try:
        with open(path, "rb") as f:
            h.update(f.read(65536))
    except OSError:
        pass
    return h.hexdigest()


def scan_library(db: Session, library: Library, progress_cb=None) -> dict:
    """
    Escanea la carpeta raíz de una biblioteca. Añade cómics nuevos, actualiza
    los que hayan cambiado (tamaño/fecha) y NO borra de la BBDD los que ya
    no encuentre en disco (los marca aparte para que el usuario decida).
    """
    stats = {"found": 0, "added": 0, "updated": 0, "unchanged": 0, "errors": []}

    existing_by_path = {c.path: c for c in library.comics}
    seen_paths = set()

    for path in _iter_comic_files(library.root_path):
        stats["found"] += 1
        seen_paths.add(path)
        try:
            st = os.stat(path)
            comic = existing_by_path.get(path)

            if comic and comic.file_size == st.st_size and comic.file_mtime == st.st_mtime:
                stats["unchanged"] += 1
                if progress_cb:
                    progress_cb(stats)
                continue

            is_new = comic is None
            if is_new:
                comic = Comic(library_id=library.id, path=path)
                db.add(comic)

            comic.filename = os.path.basename(path)
            comic.format = Path(path).suffix.lower().lstrip(".")
            comic.file_size = st.st_size
            comic.file_mtime = st.st_mtime
            comic.content_hash = _file_quick_hash(path)

            info = None
            try:
                info = archive_utils.read_comicinfo(path)
            except Exception as e:  # archivo corrupto, rar dañado, etc.
                stats["errors"].append(f"{path}: no se pudo leer ComicInfo.xml ({e})")

            if info:
                for k, v in info.items():
                    if v not in (None, ""):
                        setattr(comic, k, v)
            elif is_new:
                guess = guess_metadata_from_filename(comic.filename)
                comic.series = comic.series or guess["series"]
                comic.number = comic.number or guess["number"]
                comic.year = comic.year or guess["year"]

            try:
                comic.page_count = archive_utils.page_count(path)
            except Exception as e:
                stats["errors"].append(f"{path}: error contando páginas ({e})")

            db.flush()  # para tener comic.id antes de generar el thumbnail

            try:
                thumb = archive_utils.generate_thumbnail(comic.id, path)
                if thumb:
                    comic.cover_thumbnail = thumb
            except Exception as e:
                stats["errors"].append(f"{path}: error generando portada ({e})")

            if is_new:
                stats["added"] += 1
            else:
                stats["updated"] += 1

        except Exception as e:
            stats["errors"].append(f"{path}: {e}")

        if progress_cb:
            progress_cb(stats)

    library.last_scan_at = dt.datetime.utcnow()
    db.commit()

    stats["missing_on_disk"] = [p for p in existing_by_path if p not in seen_paths]
    return stats
