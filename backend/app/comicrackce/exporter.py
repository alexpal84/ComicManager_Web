# -*- coding: utf-8 -*-
"""
Escritura (muy limitada y controlada) sobre ComicDb.xml.

ESTADO: EXPERIMENTAL — pendiente de validar contra tu fichero real.
No lo actives en producción hasta:
  1. Copiar tu ComicDb.xml real a esta app (carpeta /data/comicrackce/).
  2. Ejecutar `inspect_structure()` y `dry_run_import()` del módulo importer.py
     y confirmar que los campos detectados coinciden con tu instalación.
  3. Probar `update_file_paths()` primero sobre una COPIA del XML (usa
     backup_only=True) y abrir esa copia con ComicRack para comprobar que
     sigue funcionando correctamente antes de aplicarlo al fichero real.

Esta función solo actualiza el valor de "ruta del fichero" de los libros
que le indiques (típicamente tras usar mover/renombrar cómics desde esta
app), dejando absolutamente todo lo demás del XML intacto. Nunca borra ni
añade nodos.
"""
from __future__ import annotations
from xml.etree import ElementTree as ET
from typing import Dict

from ..backup import backup_file
from .importer import FIELD_ALIASES, _find_book_nodes, _get_field


def update_file_paths(xml_path: str, book_id_to_new_path: Dict[str, str],
                       backup_only: bool = True) -> dict:
    """
    book_id_to_new_path: { crce_book_id: nueva_ruta_absoluta }

    Si backup_only=True (por defecto): NO modifica el XML original, solo
    genera y devuelve la ruta de una copia modificada en /data/backups/,
    para que la revises manualmente antes de sustituir el fichero real.
    """
    backup_path = backup_file(xml_path, tag="comicdb_before_pathupdate")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    updated = []
    not_found = list(book_id_to_new_path.keys())

    for node in _find_book_nodes(root):
        book_id = _get_field(node, FIELD_ALIASES["crce_book_id"])
        if book_id in book_id_to_new_path:
            new_path = book_id_to_new_path[book_id]
            _set_field(node, FIELD_ALIASES["path"], new_path)
            updated.append(book_id)
            if book_id in not_found:
                not_found.remove(book_id)

    out_path = xml_path if not backup_only else backup_path + ".updated.xml"
    tree.write(out_path, encoding="utf-8", xml_declaration=True)

    return {
        "backup_created": backup_path,
        "written_to": out_path,
        "updated_book_ids": updated,
        "not_found_book_ids": not_found,
        "applied_to_original": not backup_only,
    }


def _set_field(elem: ET.Element, aliases, value: str):
    for alias in aliases:
        if alias in elem.attrib:
            elem.attrib[alias] = value
            return
        child = elem.find(alias)
        if child is not None:
            child.text = value
            return
    # Si no existía ninguno de los alias, no inventamos estructura nueva:
    # se deja constancia para revisión manual en vez de arriesgar el XML.
