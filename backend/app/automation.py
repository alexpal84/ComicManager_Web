"""Small persisted incoming-folder pipeline.  It deliberately has no AI/filesystem agent."""
import datetime as dt
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy.orm import Session

from . import archive_utils
from .backup import backup_file
from .config import AUTOMATION_SCAN_SECONDS, AUTOMATION_STABLE_SECONDS, INCOMING_ALLOWED_ROOTS, SUPPORTED_EXTENSIONS
from .database import SessionLocal
from .filename_parser import parse_comic_filename
from .models import AutomationSettings, Comic, IncomingComic, Library
from .mover import move_comic, render_pattern
from .routers.convert import _convert_comic
from .routers.scrapers import _apply_details, _normalise_number
from .scrapers import get_scraper

_lock = threading.Lock()
_running = set()
_stop = threading.Event()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="incoming-pipeline")
_whakoom_lock = threading.Lock()
_whakoom_next_request = 0.0
WHAKOOM_REQUEST_INTERVAL = 3.0
SAFE_CANDIDATE_SCORE = 90
# A number is useful for issue matching, but complete one-shots and graphic
# novels legitimately have none.  They must not be blocked by automation.
MINIMUM_METADATA_FIELDS = ("series", "writer", "tags")


class MetadataVisionProvider:
    """Narrow future adapter: receives prepared data only, never filesystem access."""
    def verify(self, filename, suggested_metadata, candidates, images):
        raise NotImplementedError


class NullMetadataVisionProvider(MetadataVisionProvider):
    """Default safe provider. The normal deterministic pipeline never depends on AI."""
    def verify(self, filename, suggested_metadata, candidates, images):
        return None


def settings(db: Session) -> AutomationSettings:
    row = db.get(AutomationSettings, 1)
    if not row:
        row = AutomationSettings(id=1)
        db.add(row); db.commit()
    return row


def allowed_incoming_path(value: str) -> str:
    path = os.path.realpath(value)
    if not os.path.isdir(path):
        raise ValueError("La carpeta de entrada no existe o no está montada en el contenedor")
    if not any(path == root or path.startswith(root.rstrip("/") + os.sep) for root in INCOMING_ALLOWED_ROOTS):
        raise ValueError("La carpeta de entrada debe estar dentro de una ubicación permitida")
    return path


def _safe_name(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^\w\s-]", "", value.casefold()).strip()


def _meaningful_words(value):
    return {word for word in _safe_name(value).split() if len(word) > 1 and word not in {"la", "el", "de", "del", "the", "and"}}


def has_minimum_metadata(comic: Comic) -> bool:
    """Metadata sufficient to archive a comic without depending on a scraper."""
    return all(str(getattr(comic, field, "") or "").strip() for field in MINIMUM_METADATA_FIELDS)


def score_candidate(comic: Comic, candidate: dict) -> int:
    """A legible, deliberately conservative matcher; a number mismatch is fatal."""
    score = 0
    local_number, remote_number = _normalise_number(comic.number), _normalise_number(candidate.get("number"))
    if local_number and remote_number:
        if local_number != remote_number:
            return 0
        score += 50
    local_series, remote_series = _safe_name(comic.series), _safe_name(candidate.get("series") or candidate.get("title"))
    if local_series and remote_series:
        if local_series == remote_series: score += 35
        elif local_series in remote_series or remote_series in local_series: score += 20
        else:
            local_words, remote_words = _meaningful_words(local_series), _meaningful_words(remote_series)
            overlap = local_words & remote_words
            # Editions frequently add a subtitle ("de Geoff Johns", publisher,
            # omnibus, etc.). Keep those candidates for review instead of hiding
            # them, while never treating this weaker relation as automatically safe.
            if not overlap:
                return 0
            score += 15 + min(10, 5 * len(overlap))
    if comic.volume and str(comic.volume) == str(candidate.get("volume") or ""): score += 8
    if comic.year and str(comic.year) == str(candidate.get("year") or ""): score += 5
    if comic.publisher and _safe_name(comic.publisher) == _safe_name(candidate.get("publisher")): score += 4
    if comic.title and _safe_name(comic.title) == _safe_name(candidate.get("title")): score += 5
    return score


def _serialise(candidate, source, score):
    return {"id": candidate.get("url") or candidate.get("ref"), "source": source, "score": score,
            "ref": candidate.get("url") or candidate.get("ref"), "cover_url": candidate.get("cover_url"),
            "series": candidate.get("series", ""), "number": candidate.get("number", ""),
            "volume": candidate.get("volume", ""), "title": candidate.get("title", ""),
            "publisher": candidate.get("publisher", ""), "year": candidate.get("year", "")}


def _whakoom_call(callback):
    """One request at a time, deliberately spaced to avoid rate limiting."""
    global _whakoom_next_request
    with _whakoom_lock:
        wait = _whakoom_next_request - time.monotonic()
        if wait > 0: time.sleep(wait)
        try:
            return callback()
        finally:
            _whakoom_next_request = time.monotonic() + WHAKOOM_REQUEST_INTERVAL


def _search_queries(comic: Comic):
    """Small, explainable fallbacks for editions whose series includes a subtitle."""
    series = (comic.series or "").strip()
    if not series:
        return []
    queries = [series]
    # Preserve the order visible to the user for the core series name.
    core = re.split(r"\s*(?:[:·\-–—]|\[)", series, maxsplit=1)[0].strip()
    if core and _safe_name(core) != _safe_name(series):
        queries.append(core)
    if comic.writer and core:
        surname = re.split(r"\s*(?:,|;|&| y | and )\s*", comic.writer.strip())[0].split()[-1]
        if surname:
            queries.append(f"{core} {surname}")
    # De-duplicate normalized variants and cap the work per scraper.
    unique = []
    for query in queries:
        if query and _safe_name(query) not in {_safe_name(existing) for existing in unique}:
            unique.append(query)
    return unique[:3]


def _find_candidates(comic):
    candidates, errors = [], []
    # The remote search is by series. The issue number is compared locally below.
    queries = _search_queries(comic)
    if not queries:
        return candidates, ["Falta Serie para buscar candidatos"]
    for source in ("whakoom", "comicvine"):
        try:
            scraper = get_scraper(source)
            search = []
            for query in queries:
                results = _whakoom_call(lambda query=query: scraper.search(query)) if source == "whakoom" else scraper.search(query)
                search.extend(results)
                # A direct result avoids unnecessary fallback requests.
                if any(_safe_name(row.get("series") or row.get("title")) == _safe_name(comic.series) for row in results):
                    break
            deduplicated = {row.get("ref"): row for row in search if row.get("ref")}
            # Only inspect the most plausible series. This prevents N series × all issues requests.
            ranked_series = sorted(deduplicated.values(), key=lambda series: -score_candidate(comic, series))[:2]
            for series in ranked_series:
                if source == "whakoom": issues = _whakoom_call(lambda ref=series["ref"]: scraper.get_series_issues(ref))
                else: issues = scraper.get_volume_issues(series["ref"].split(":", 1)[-1])
                for issue in issues:
                    item = {**series, **issue, "series": series.get("series") or series.get("title", "")}
                    score = score_candidate(comic, item)
                    if score: candidates.append(_serialise(item, source, score))
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:30], errors


def _set(item, status, step, error=None):
    item.status, item.last_step, item.error = status, step, error


def _apply_suggestions(comic):
    values = parse_comic_filename(comic.path)
    mapping = {"series": "series", "number": "number", "volume": "volume", "title": "title", "year": "year", "format": "format_tag"}
    for source, target in mapping.items():
        if values.get(source) not in (None, "") and getattr(comic, target) in (None, ""):
            setattr(comic, target, values[source])
    comic.metadata_dirty = True


def _repair_filename_identity(comic):
    """Correct only an old, clearly parser-produced trailing 'Tomo' identity."""
    values = parse_comic_filename(comic.path)
    if values.get("series") and re.search(r"\b(?:tomo|tome)\s*$", comic.series or "", re.I):
        comic.series = values["series"]
    if values.get("number") and not comic.number:
        comic.number = values["number"]
    if values.get("title") and not comic.title:
        comic.title = values["title"]


def _write_xml(comic):
    if comic.format != "cbz": raise ValueError("ComicInfo.xml solo se puede escribir en CBZ")
    backup_file(comic.path, tag="before_automation_comicinfo_write")
    archive_utils.write_comicinfo_into_cbz(comic.path, comic)
    comic.comicinfo_synced_at = dt.datetime.utcnow(); comic.comicinfo_written = True; comic.metadata_dirty = False


def process_item(item_id: int, force=False):
    with _lock:
        if item_id in _running: return
        _running.add(item_id)
    db = SessionLocal()
    try:
        item, cfg = db.get(IncomingComic, item_id), settings(db)
        if not item or (not cfg.enabled and not force): return
        if not os.path.exists(item.source_path): raise FileNotFoundError("El archivo de origen ya no existe")
        _set(item, "Procesando", item.last_step); db.commit()
        comic = db.get(Comic, item.comic_id) if item.comic_id else None
        if not comic:
            library = db.get(Library, cfg.target_library_id) if cfg.target_library_id else db.query(Library).first()
            if not library: raise ValueError("Configura una biblioteca destino antes de procesar")
            stat = os.stat(item.source_path)
            comic = Comic(library_id=library.id, path=item.source_path, filename=os.path.basename(item.source_path),
                          format=Path(item.source_path).suffix.lower().lstrip("."), file_size=stat.st_size, file_mtime=stat.st_mtime,
                          page_count=archive_utils.page_count(item.source_path))
            db.add(comic); db.flush(); comic.cover_thumbnail = archive_utils.generate_thumbnail(comic.id, comic.path)
            item.comic_id = comic.id; item.last_step = "importado"; db.commit()
        # Incoming files are imported directly, unlike a library scan. Read an
        # embedded ComicInfo.xml here before considering filename guesses or a
        # scraper, so complete source metadata is authoritative.
        try:
            embedded_metadata = archive_utils.read_comicinfo(comic.path)
        except Exception:
            embedded_metadata = None
        if embedded_metadata:
            for field, value in embedded_metadata.items():
                if value not in (None, ""):
                    setattr(comic, field, value)
            comic.comicinfo_written = True
            comic.metadata_dirty = False
            db.commit()
        _repair_filename_identity(comic); db.commit()
        def enabled_now():
            if force or db.get(AutomationSettings, 1).enabled: return True
            _set(item, "Esperando", item.last_step); db.commit()
            return False
        if cfg.accept_suggestions and item.last_step in ("detectado", "importado"):
            if not enabled_now(): return
            _set(item, "Valores propuestos", "propuestas"); _apply_suggestions(comic); db.commit(); item.last_step = "propuestas"; db.commit()
        if cfg.convert and comic.format in ("cbr", "rar") and item.last_step in ("importado", "propuestas"):
            if not enabled_now(): return
            _set(item, "Convirtiendo", "convirtiendo"); db.commit()
            _convert_comic(comic, False, db); item.source_path = comic.path; item.source_filename = comic.filename; item.last_step = "convertido"; db.commit()
        # A scraper enriches metadata but is never a prerequisite for a comic
        # which already has the minimum archive identity.
        if item.last_step in ("importado", "propuestas", "convertido", "candidatos") and has_minimum_metadata(comic):
            item.last_step = "metadatos"; item.candidates_json = "[]"; db.commit()
        selected = json.loads(item.selected_candidate_json or "null")
        if item.last_step == "candidatos" and selected:
            # A prior metadata-detail request may have been rate-limited. Reuse its selected candidate.
            _set(item, "Buscando metadatos", "detalles"); db.commit()
            scraper = get_scraper(selected["source"])
            details = _whakoom_call(lambda: scraper.get_details(selected["ref"])) if selected["source"] == "whakoom" else scraper.get_details(selected["ref"])
            _apply_details(comic, details, "fill_empty"); comic.source_scraper, comic.source_url = selected["source"], selected["ref"]
            item.last_step = "metadatos"; db.commit()
        elif cfg.scrape and item.last_step in ("importado", "propuestas", "convertido", "candidatos"):
            if not enabled_now(): return
            _set(item, "Buscando metadatos", "buscando"); db.commit()
            found, scraper_errors = _find_candidates(comic); item.candidates_json = json.dumps(found); item.last_step = "candidatos"; db.commit()
            if scraper_errors and not found:
                raise RuntimeError("; ".join(scraper_errors))
            best = found[0] if found else None
            if not best or best["score"] < SAFE_CANDIDATE_SCORE:
                _set(item, "Necesita revisión", "candidatos"); db.commit(); return
            item.selected_candidate_json = json.dumps(best); item.selected_manually = False; db.commit()
            scraper = get_scraper(best["source"]); details = _whakoom_call(lambda: scraper.get_details(best["ref"])) if best["source"] == "whakoom" else scraper.get_details(best["ref"])
            _apply_details(comic, details, "fill_empty"); comic.source_scraper, comic.source_url = best["source"], best["ref"]
            item.last_step = "metadatos"; db.commit()
        if cfg.write_comicinfo and item.last_step == "metadatos":
            if not enabled_now(): return
            _set(item, "Actualizando ComicInfo.xml", "xml"); db.commit(); _write_xml(comic); item.last_step = "xml"; db.commit()
        pattern = cfg.destination_pattern
        item.planned_destination = os.path.join(comic.library.root_path, render_pattern(comic, pattern) + Path(comic.path).suffix)
        if cfg.move and item.last_step in ("metadatos", "xml"):
            if not enabled_now(): return
            selected = json.loads(item.selected_candidate_json or "{}")
            if cfg.move_only_safe and not has_minimum_metadata(comic) and selected.get("score", 0) < SAFE_CANDIDATE_SCORE:
                _set(item, "Necesita revisión", "metadatos"); db.commit(); return
            _set(item, "Moviendo", "moviendo"); db.commit(); move_comic(db, comic, render_pattern(comic, pattern)); item.source_path = comic.path; item.last_step = "movido"; db.commit()
        _set(item, "Completado", item.last_step); db.commit()
    except Exception as exc:
        db.rollback(); item = db.get(IncomingComic, item_id)
        if item: _set(item, "Error", item.last_step, str(exc)); db.commit()
    finally:
        db.close()
        with _lock: _running.discard(item_id)


def enqueue(item_id: int, force=False):
    """Serial queue: no burst of archive/database/scraper work."""
    return _executor.submit(process_item, item_id, force)


def detect_once(force=False):
    db = SessionLocal()
    try:
        cfg = settings(db)
        # A manual scan from the review workspace must be useful even when the
        # background watcher is paused.  `force` never starts processing by
        # itself; it only registers stable files for the user to review.
        if not cfg.enabled and not force: return 0
        root = allowed_incoming_path(cfg.incoming_path)
        now = dt.datetime.utcnow()
        detected = 0
        for entry in Path(root).iterdir():
            if not entry.is_file() or entry.suffix.lower() not in SUPPORTED_EXTENSIONS or entry.name.startswith((".", "~")) or entry.suffix.lower() in {".part", ".tmp"}: continue
            stat = entry.stat(); item = db.query(IncomingComic).filter_by(source_path=str(entry)).first()
            if not item:
                item = IncomingComic(source_path=str(entry), source_filename=entry.name, file_size=stat.st_size, file_mtime=stat.st_mtime, stable_since=now)
                db.add(item); db.commit(); detected += 1; continue
            if item.status in ("Completado", "Omitido"): continue
            if item.file_size != stat.st_size or item.file_mtime != stat.st_mtime:
                item.file_size, item.file_mtime, item.stable_since = stat.st_size, stat.st_mtime, now; _set(item, "Esperando", "estable"); db.commit(); continue
            if item.stable_since and (now - item.stable_since).total_seconds() >= AUTOMATION_STABLE_SECONDS and item.status in ("Nuevo", "Esperando"):
                item.status = "Esperando"; db.commit(); enqueue(item.id)
        return detected
    finally: db.close()


def run_worker():
    while not _stop.wait(AUTOMATION_SCAN_SECONDS):
        try: detect_once()
        except Exception: pass


def start_worker():
    threading.Thread(target=run_worker, daemon=True, name="incoming-comics").start()
