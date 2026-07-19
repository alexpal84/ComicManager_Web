"""
Manejo de archivos de cómic (cbz = zip, cbr = rar, cb7 = 7z).

Requiere el binario `unrar` (o `unar`) instalado en el sistema para poder
leer/extraer archivos .cbr — se instala en el Dockerfile.
"""
from __future__ import annotations
import io
import os
import re
import shutil
import zipfile
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple

import rarfile
from PIL import Image

from .config import THUMBNAIL_MAX_SIDE, COVERS_DIR
from .comicinfo import parse_comicinfo_xml, comic_to_comicinfo_xml

# El binario disponible depende de qué paquete haya podido instalarse en el
# contenedor: el "unrar" real (no-libre, mejor compatibilidad) o su clon
# libre "unrar-free" (ver Dockerfile). Detectamos cuál hay disponible.
if shutil.which("unrar"):
    rarfile.UNRAR_TOOL = "unrar"
elif shutil.which("unrar-free"):
    rarfile.UNRAR_TOOL = "unrar-free"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
COMICINFO_NAME = "ComicInfo.xml"


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _open_archive(path: str):
    ext = Path(path).suffix.lower()
    if ext in (".cbz", ".zip"):
        return zipfile.ZipFile(path, "r"), "zip"
    if ext in (".cbr", ".rar"):
        return rarfile.RarFile(path, "r"), "rar"
    raise ValueError(f"Formato de archivo no soportado: {ext}")


def list_image_names(path: str) -> List[str]:
    archive, _ = _open_archive(path)
    try:
        names = [n for n in archive.namelist() if Path(n).suffix.lower() in IMAGE_EXTS and not n.startswith("__MACOSX")]
        return sorted(names, key=_natural_key)
    finally:
        archive.close()


def read_comicinfo(path: str) -> Optional[dict]:
    archive, _ = _open_archive(path)
    try:
        for name in archive.namelist():
            if Path(name).name.lower() == COMICINFO_NAME.lower():
                data = archive.read(name)
                return parse_comicinfo_xml(data)
        return None
    finally:
        archive.close()


def extract_cover_bytes(path: str) -> Optional[bytes]:
    archive, _ = _open_archive(path)
    try:
        images = [n for n in archive.namelist() if Path(n).suffix.lower() in IMAGE_EXTS and not n.startswith("__MACOSX")]
        if not images:
            return None
        images.sort(key=_natural_key)
        return archive.read(images[0])
    finally:
        archive.close()


def generate_thumbnail(comic_id: int, path: str) -> Optional[str]:
    """Extrae la portada y genera una miniatura en COVERS_DIR. Devuelve la ruta relativa."""
    data = extract_cover_bytes(path)
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        img.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE * 2))
        out_name = f"{comic_id}.jpg"
        out_path = COVERS_DIR / out_name
        img.save(out_path, "JPEG", quality=85)
        return out_name
    except Exception:
        return None


def page_count(path: str) -> int:
    try:
        return len(list_image_names(path))
    except Exception:
        return 0


def read_page_bytes(path: str, page_index: int) -> Tuple[bytes, str]:
    names = list_image_names(path)
    if page_index < 0 or page_index >= len(names):
        raise IndexError("Página fuera de rango")
    name = names[page_index]
    archive, _ = _open_archive(path)
    try:
        data = archive.read(name)
        ext = Path(name).suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}.get(ext, "application/octet-stream")
        return data, mime
    finally:
        archive.close()


def convert_cbr_to_cbz(src_path: str, delete_original: bool = False) -> str:
    """
    Convierte un .cbr en un .cbz equivalente (mismo nombre, extensión cbz),
    en el mismo directorio. Verifica el número de páginas antes de borrar el
    original. Devuelve la ruta del nuevo .cbz.
    """
    src = Path(src_path)
    if src.suffix.lower() not in (".cbr", ".rar"):
        raise ValueError("El archivo de origen no es un .cbr")

    dst = src.with_suffix(".cbz")
    if dst.exists():
        raise FileExistsError(f"Ya existe un archivo destino: {dst}")

    src_pages = page_count(str(src))

    with tempfile.TemporaryDirectory() as tmpdir:
        rf = rarfile.RarFile(str(src), "r")
        try:
            rf.extractall(tmpdir)
        finally:
            rf.close()

        tmp_dst = dst.parent / (dst.stem + ".tmpconv.cbz")
        with zipfile.ZipFile(tmp_dst, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                for fname in files:
                    full = os.path.join(root, fname)
                    arcname = os.path.relpath(full, tmpdir)
                    zf.write(full, arcname)

        new_pages = page_count(str(tmp_dst))
        if new_pages != src_pages or new_pages == 0:
            tmp_dst.unlink(missing_ok=True)
            raise RuntimeError(
                f"Verificación fallida: el cbz generado tiene {new_pages} páginas, "
                f"el cbr original tenía {src_pages}. No se ha borrado el original."
            )

        shutil.move(str(tmp_dst), str(dst))

    if delete_original:
        src.unlink()

    return str(dst)


def write_comicinfo_into_cbz(cbz_path: str, comic) -> None:
    """
    Escribe/actualiza ComicInfo.xml dentro de un .cbz existente.
    Estrategia segura: crea un zip nuevo con todo el contenido + el
    ComicInfo.xml actualizado, y solo si todo va bien reemplaza el original.
    """
    path = Path(cbz_path)
    if path.suffix.lower() != ".cbz":
        raise ValueError("Solo se puede escribir ComicInfo.xml en archivos .cbz. Convierte el .cbr primero.")

    xml_bytes = comic_to_comicinfo_xml(comic)
    tmp_path = path.with_suffix(".cbz.tmp")

    with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
        replaced = False
        for item in zin.infolist():
            if Path(item.filename).name.lower() == COMICINFO_NAME.lower():
                zout.writestr(item, xml_bytes)
                replaced = True
            else:
                zout.writestr(item, zin.read(item.filename))
        if not replaced:
            zout.writestr(COMICINFO_NAME, xml_bytes)

    shutil.move(str(tmp_path), str(path))
