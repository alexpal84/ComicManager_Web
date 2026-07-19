"""
Serialización del fichero ComicInfo.xml, el estándar que usa (Community
Edition incluida) para guardar metadatos dentro del propio cbz/cbr.
Referencia del esquema: https://anansi-project.github.io/docs/comicinfo/documentation
"""
from __future__ import annotations
from xml.etree import ElementTree as ET
from xml.dom import minidom
from typing import Optional

# Orden y nombres de los tags tal cual los espera ComicRack(CE)
FIELD_MAP = [
    ("Title", "title"),
    ("Series", "series"),
    ("Number", "number"),
    ("Count", "count"),
    ("Volume", "volume"),
    ("AlternateSeries", None),
    ("SeriesGroup", "series_group"),
    ("StoryArc", "story_arc"),
    ("Summary", "summary"),
    ("Notes", "notes"),
    ("Year", "year"),
    ("Month", "month"),
    ("Day", "day"),
    ("Writer", "writer"),
    ("Penciller", "penciller"),
    ("Inker", "inker"),
    ("Colorist", "colorist"),
    ("Letterer", "letterer"),
    ("CoverArtist", "cover_artist"),
    ("Editor", "editor"),
    ("Publisher", "publisher"),
    ("Imprint", "imprint"),
    ("Genre", "genre"),
    ("Web", "web"),
    ("PageCount", "page_count"),
    ("LanguageISO", "language"),
    ("Format", "format_tag"),
    ("BlackAndWhite", "black_and_white"),
    ("Manga", "manga"),
    ("Characters", "characters"),
    ("Teams", "teams"),
    ("Locations", "locations"),
    ("AgeRating", "age_rating"),
    ("CommunityRating", "community_rating"),
    ("Tags", "tags"),
]


def comic_to_comicinfo_xml(comic) -> bytes:
    """Genera el contenido (bytes utf-8) de ComicInfo.xml a partir de un objeto Comic (ORM)."""
    root = ET.Element("ComicInfo")
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")

    for xml_tag, attr in FIELD_MAP:
        if attr is None:
            continue
        value = getattr(comic, attr, None)
        if value is None or value == "":
            continue
        el = ET.SubElement(root, xml_tag)
        el.text = str(value)

    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    return pretty


def parse_comicinfo_xml(xml_bytes: bytes) -> dict:
    """Parsea un ComicInfo.xml y devuelve un dict con los nombres de campo internos."""
    result: dict = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return result

    reverse_map = {tag: attr for tag, attr in FIELD_MAP if attr}
    for child in root:
        tag = child.tag
        attr = reverse_map.get(tag)
        if not attr:
            continue
        text = (child.text or "").strip()
        if attr in ("year", "month", "day", "count", "page_count"):
            try:
                result[attr] = int(text) if text else None
            except ValueError:
                result[attr] = None
        elif attr == "community_rating":
            try:
                result[attr] = float(text) if text else None
            except ValueError:
                result[attr] = None
        else:
            result[attr] = text
    return result
