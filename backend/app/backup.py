import shutil
import datetime as dt
from pathlib import Path

from .config import BACKUPS_DIR


def backup_file(path: str, tag: str = "") -> str:
    """
    Copia el fichero indicado a /data/backups/ con timestamp, antes de
    modificarlo. Nunca sobreescribe backups anteriores. Devuelve la ruta
    del backup creado (o cadena vacía si el fichero origen no existe).
    """
    src = Path(path)
    if not src.exists():
        return ""
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix = f"_{tag}" if tag else ""
    dst_name = f"{src.stem}{suffix}_{stamp}{src.suffix}"
    dst = BACKUPS_DIR / dst_name
    shutil.copy2(src, dst)
    return str(dst)


def backup_database(db_path: str) -> str:
    return backup_file(db_path, tag="db")
