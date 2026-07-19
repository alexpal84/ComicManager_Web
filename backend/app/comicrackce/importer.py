# -*- coding: utf-8 -*-
"""
Importador desde ComicDb.xml (la base de datos de ComicRack / ComicRackCE).

IMPORTANTE — estado de este módulo
-----------------------------------
No hemos podido inspeccionar tu ComicDb.xml real (está en tu PC, sin acceso
remoto en el momento de construir esta app). Este importador es, por tanto,
un "mejor esfuerzo" basado en la estructura pública conocida del formato de
ComicRack: un árbol XML con un nodo por cómic ("Book"), con atributos o
sub-nodos como FilePath, Series, Number, Volume, Year, Writer, Penciller...

Este módulo:
  1. NUNCA escribe en el ComicDb.xml. Solo lo lee.
  2. Hace SIEMPRE una copia de seguridad del XML antes de tocarlo (por si en
     el futuro se añade un exportador), aunque de momento solo se lee.
  3. Genera un informe de "dry run" (qué encontraría, con cuántas
     coincidencias) antes de tocar nuestra propia base de datos.
  4. Empareja libros del XML con cómics ya escaneados en nuestra BBDD por
     ruta de fichero normalizada (y si no coincide exacta, por nombre de
     fichero), nunca al revés.

Cuando tengas acceso de nuevo al ComicDb.xml real, ejecuta primero
`inspect_structure()` sobre él y compara con lo que se espera aquí — es
muy probable que haya que ajustar `BOOK_TAG_CANDIDATES` y `FIELD_ALIASES`
a la estructura exacta de tu versión de ComicRackCE.
"""
from __future__ import annotations
import os
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import Dict, List, Any, Optional

from sqlalchemy.orm import Session

from ..backup import backup_file
from ..models import Comic

# Nombres de nodo que probablemente representen "un cómic" dentro del XML.
BOOK_TAG_CANDIDATES = {"book", "comicbook", "comic", "item"}

# Alias conocidos/probables de cada campo -> nuestro nombre interno.
# Se buscan tanto como ATRIBUTO del nodo Book como como HIJO <Tag>valor</Tag>.
FIELD_ALIASES: Dict[str, List[str]] = {
    "path": ["FilePath", "Path", "File", "FileName"],
    "series": ["Series", "SeriesName"],
    "number": ["Number", "IssueNumber"],
    "volume": ["Volume"],
    "title": ["Title"],
    "year": ["Year"],
    "month": ["Month"],
    "day": ["Day"],
    "publisher": ["Publisher"],
    "genre": ["Genre", "Genres"],
    "writer": ["Writer", "Writers"],
    "penciller": ["Penciller", "Pencillers"],
    "inker": ["Inker", "Inkers"],
    "colorist": ["Colorist", "Colorists"],
    "letterer": ["Letterer"],
    "cover_artist": ["CoverArtist"],
    "editor": ["Editor"],
    "summary": ["Summary", "Description"],
    "notes": ["Notes"],
    "tags": ["Tags"],
    "rating": ["Rating", "UserRating"],
    "read": ["Read", "IsRead"],
    "crce_book_id": ["Id", "BookId", "Guid"],
}


def inspect_structure(xml_path: str, max_nodes: int = 5) -> dict:
    """
    Herramienta de diagnóstico: recorre el XML y devuelve un resumen de qué
    tags existen y con qué frecuencia, para poder ajustar BOOK_TAG_CANDIDATES
    y FIELD_ALIASES a la estructura real sin haber tenido que verla antes.
    NO requiere que el formato coincida con lo esperado.
    """
    tag_counts: Dict[str, int] = {}
    samples: Dict[str, list] = {}

    for _event, elem in ET.iterparse(xml_path, events=("end",)):
        tag = elem.tag.split("}")[-1]  # quita namespace si lo hay
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if len(samples.get(tag, [])) < max_nodes:
            sample = {"attrib": dict(elem.attrib)}
            children = {c.tag.split("}")[-1]: (c.text or "").strip() for c in list(elem)[:20]}
            sample["children"] = children
            samples.setdefault(tag, []).append(sample)
        elem.clear()

    return {"tag_counts": tag_counts, "samples": samples}


def _get_field(elem: ET.Element, aliases: List[str]) -> Optional[str]:
    for alias in aliases:
        if alias in elem.attrib:
            return elem.attrib[alias]
        child = elem.find(alias)
        if child is not None and child.text:
            return child.text.strip()
    return None


def _find_book_nodes(root: ET.Element) -> List[ET.Element]:
    nodes = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1].lower()
        if tag in BOOK_TAG_CANDIDATES and _get_field(elem, FIELD_ALIASES["path"]):
            nodes.append(elem)
    return nodes


def parse_comicdb_xml(xml_path: str) -> List[Dict[str, Any]]:
    """Lee (solo lectura) el ComicDb.xml y devuelve una lista de dicts por libro."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    books = []
    for node in _find_book_nodes(root):
        entry: Dict[str, Any] = {}
        for field, aliases in FIELD_ALIASES.items():
            val = _get_field(node, aliases)
            if val is not None:
                entry[field] = val
        if entry.get("path"):
            books.append(entry)
    return books


def dry_run_import(db: Session, xml_path: str) -> dict:
    """
    Genera un informe SIN modificar nada: cuántos libros hay en el XML,
    cuántos casan por ruta exacta con cómics ya escaneados, cuántos por
    nombre de fichero, y cuántos no se encuentran en absoluto.
    """
    backup_path = backup_file(xml_path, tag="comicdb_dryrun")

    books = parse_comicdb_xml(xml_path)
    existing_by_path = {c.path: c for c in db.query(Comic).all()}
    existing_by_filename = {}
    for c in existing_by_path.values():
        existing_by_filename.setdefault(os.path.basename(c.path).lower(), []).append(c)

    exact_matches, filename_matches, no_matches = [], [], []
    for book in books:
        path = book["path"]
        norm_path = os.path.normpath(path)
        if norm_path in existing_by_path:
            exact_matches.append(book)
            continue
        fname = os.path.basename(path).lower()
        if fname in existing_by_filename:
            filename_matches.append(book)
            continue
        no_matches.append(book)

    return {
        "backup_created": backup_path,
        "total_books_in_xml": len(books),
        "exact_path_matches": len(exact_matches),
        "filename_only_matches": len(filename_matches),
        "no_match": len(no_matches),
        "no_match_sample": no_matches[:20],
    }


def apply_import(db: Session, xml_path: str, match_by: str = "path") -> dict:
    """
    Aplica la importación a NUESTRA base de datos (nunca modifica el
    ComicDb.xml). match_by: "path" (exacto) o "filename" (más laxo).
    Solo rellena campos que estén vacíos en nuestra BBDD, para no pisar
    ediciones ya hechas desde esta aplicación.
    """
    books = parse_comicdb_xml(xml_path)
    existing_by_path = {os.path.normpath(c.path): c for c in db.query(Comic).all()}
    existing_by_filename: Dict[str, List[Comic]] = {}
    for c in existing_by_path.values():
        existing_by_filename.setdefault(os.path.basename(c.path).lower(), []).append(c)

    updated = 0
    skipped = 0
    for book in books:
        comic = None
        norm_path = os.path.normpath(book["path"])
        if norm_path in existing_by_path:
            comic = existing_by_path[norm_path]
        elif match_by == "filename":
            candidates = existing_by_filename.get(os.path.basename(book["path"]).lower())
            if candidates and len(candidates) == 1:
                comic = candidates[0]

        if not comic:
            skipped += 1
            continue

        for field, value in book.items():
            if field == "path":
                continue
            current = getattr(comic, field, None)
            if not current and value not in (None, ""):
                setattr(comic, field, _coerce_value(field, value))
        comic.crce_book_id = book.get("crce_book_id", comic.crce_book_id)
        updated += 1

    db.commit()
    return {"updated": updated, "skipped": skipped}
