import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from .database import SessionLocal
from .models import Comic

executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="comic-task")
_lock = threading.Lock()
_tasks = {}

def submit(kind, comic_ids, worker):
    task_id = uuid.uuid4().hex
    with _lock:
        _tasks[task_id] = {"id": task_id, "kind": kind, "total": len(comic_ids), "done": 0,
                           "ok": 0, "failed": 0, "status": "queued", "items": []}
    executor.submit(_run, task_id, kind, list(comic_ids), worker)
    return task_id

def _run(task_id, kind, comic_ids, worker):
    with _lock: _tasks[task_id]["status"] = "running"
    for comic_id in comic_ids:
        db = SessionLocal(); comic = db.query(Comic).get(comic_id)
        try:
            if not comic: raise ValueError("Cómic no encontrado")
            comic.operation_status, comic.operation_error = kind, None
            db.commit()
            result = worker(comic, db) or {}
            comic.operation_status, comic.operation_error = "idle", None
            db.commit(); item = {"comic_id": comic_id, "ok": True, **result}
            with _lock: _tasks[task_id]["ok"] += 1
        except Exception as exc:
            db.rollback(); comic = db.query(Comic).get(comic_id)
            if comic:
                comic.operation_status, comic.operation_error = "error", str(exc); db.commit()
            item = {"comic_id": comic_id, "ok": False, "error": str(exc)}
            with _lock: _tasks[task_id]["failed"] += 1
        finally: db.close()
        with _lock:
            _tasks[task_id]["done"] += 1; _tasks[task_id]["items"].append(item)
    with _lock: _tasks[task_id]["status"] = "completed"

def get(task_id):
    with _lock: return dict(_tasks[task_id]) if task_id in _tasks else None

def active():
    with _lock: return [dict(task) for task in _tasks.values() if task["status"] != "completed"]
