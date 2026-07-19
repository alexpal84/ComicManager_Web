import os
import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Comic


def _sanitize_path_component(text: str) -> str:
    text = text or ""
    text = re.sub(r'[<>:"|?*]', "_", text)
    text = text.replace("/", "-").replace("\\", "-")
    return text.strip()


def render_pattern(comic: Comic, pattern: str) -> str:
    """
    Sustituye tokens tipo {series}, {number}, {year}, {publisher}, {volume}
    por los valores del cómic. El resultado es una ruta RELATIVA (sin
    extensión, se añade automáticamente la del fichero original).
    """
    values = {
        "series": comic.series or "Sin serie",
        "number": comic.number or "0",
        "year": comic.year or "s.f.",
        "publisher": comic.publisher or "Sin editorial",
        "volume": comic.volume or "",
        "title": comic.title or "",
    }
    rendered = pattern
    for key, val in values.items():
        rendered = rendered.replace("{%s}" % key, _sanitize_path_component(str(val)))
    parts = [p for p in rendered.split("/") if p != ""]
    parts = [_sanitize_path_component(p) for p in parts]
    return os.path.join(*parts) if parts else comic.filename


def move_comic(db: Session, comic: Comic, new_relative_path: str) -> str:
    """
    Mueve físicamente el fichero del cómic dentro de su misma biblioteca
    (root_path) a la nueva ruta relativa indicada, y actualiza la BBDD.
    """
    library_root = comic.library.root_path
    ext = Path(comic.path).suffix
    if not new_relative_path.lower().endswith(ext.lower()):
        new_relative_path = new_relative_path + ext

    new_abs_path = os.path.normpath(os.path.join(library_root, new_relative_path))

    # Seguridad: no permitir salir de la carpeta raíz de la biblioteca
    if not new_abs_path.startswith(os.path.normpath(library_root)):
        raise ValueError("La ruta destino queda fuera de la biblioteca")

    if os.path.exists(new_abs_path):
        raise FileExistsError(f"Ya existe un archivo en el destino: {new_abs_path}")

    os.makedirs(os.path.dirname(new_abs_path), exist_ok=True)
    shutil.move(comic.path, new_abs_path)

    comic.path = new_abs_path
    comic.filename = os.path.basename(new_abs_path)
    db.commit()
    return new_abs_path
