# -*- coding: utf-8 -*-
"""
Scraper de ComicVine usando la API oficial y pública de comicvine.gamespot.com.
Documentación: https://comicvine.gamespot.com/api/documentation

Requiere una API key personal y gratuita, configurable con la variable de
entorno COMICVINE_API_KEY. No reutiliza el binario .NET del plugin original
de ComicRackCE (no es portable a un backend Python), pero replica el mismo
flujo funcional: búsqueda de volumen/número -> selección -> importación de
metadatos + portada.
"""
from __future__ import annotations
import re
from typing import List, Dict, Any

import requests

from .base import BaseScraper
from ..config import COMICVINE_API_KEY, COMICVINE_BASE_URL


class ComicVineNotConfigured(Exception):
    pass


class ComicVineScraper(BaseScraper):
    name = "comicvine"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or COMICVINE_API_KEY
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ComicManager/1.0 (uso personal)"})

    def _get(self, endpoint: str, params: dict) -> dict:
        if not self.api_key:
            raise ComicVineNotConfigured(
                "No hay API key de ComicVine configurada. Define la variable de entorno "
                "COMICVINE_API_KEY con tu clave gratuita de https://comicvine.gamespot.com/api/"
            )
        params = dict(params)
        params["api_key"] = self.api_key
        params["format"] = "json"
        resp = self.session.get(f"{COMICVINE_BASE_URL}/{endpoint}", params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Busca volúmenes (series) que coincidan con la query. Si la query
        incluye un número de issue (p.ej. "Batman 45"), se separa y se
        devuelve como pista para el frontend, pero la búsqueda principal
        es siempre por volumen/serie, como hace el scraper original.
        """
        m = re.match(r"^(.*?)(?:\s+#?(\d+(?:\.\d+)?))?$", query.strip())
        series_query = m.group(1).strip() if m else query
        hint_number = m.group(2) if m else None

        data = self._get("search", {
            "query": series_query,
            "resources": "volume",
            "limit": 15,
            "field_list": "id,name,start_year,publisher,image,site_detail_url,description,count_of_issues",
        })

        results = []
        for item in data.get("results", []):
            results.append({
                "ref": f"volume:{item.get('id')}",
                "title": item.get("name", ""),
                "series": item.get("name", ""),
                "publisher": (item.get("publisher") or {}).get("name", ""),
                "year": item.get("start_year", ""),
                "issue_count": item.get("count_of_issues"),
                "cover_url": (item.get("image") or {}).get("small_url"),
                "source": "ComicVine",
                "hint_number": hint_number,
            })
        return results

    def get_volume_issues(self, volume_id: str) -> List[Dict[str, Any]]:
        data = self._get("issues", {
            "filter": f"volume:{volume_id}",
            "sort": "issue_number:asc",
            "limit": 100,
            "field_list": "id,issue_number,name,cover_date,image",
        })
        return [
            {
                "ref": f"issue:{it['id']}",
                "number": it.get("issue_number", ""),
                "title": it.get("name") or "",
                "date": it.get("cover_date"),
                "cover_url": (it.get("image") or {}).get("small_url"),
            }
            for it in data.get("results", [])
        ]

    def get_details(self, ref: str) -> Dict[str, Any]:
        if not ref.startswith("issue:"):
            raise ValueError("Se esperaba una referencia 'issue:<id>'. Usa primero get_volume_issues().")
        issue_id = ref.split(":", 1)[1]

        data = self._get(f"issue/4000-{issue_id}", {
            "field_list": "id,name,issue_number,cover_date,description,image,volume,"
                          "person_credits,character_credits,team_credits,location_credits,story_arc_credits",
        })
        it = data.get("results", {})
        if not it:
            raise ValueError("Issue no encontrado en ComicVine")

        credits_by_role = {"writer": [], "penciller": [], "inker": [], "colorist": [], "letterer": [], "cover_artist": [], "editor": []}
        role_map = {
            "writer": "writer", "penciller": "penciller", "artist": "penciller",
            "inker": "inker", "colorist": "colorist", "letterer": "letterer",
            "cover": "cover_artist", "editor": "editor",
        }
        for person in it.get("person_credits", []) or []:
            role_raw = (person.get("role") or "").lower()
            name = person.get("name", "")
            for key, internal in role_map.items():
                if key in role_raw:
                    credits_by_role[internal].append(name)

        cover_date = it.get("cover_date") or ""
        year = month = day = None
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", cover_date)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))

        characters = ", ".join(c.get("name", "") for c in (it.get("character_credits") or []))
        teams = ", ".join(c.get("name", "") for c in (it.get("team_credits") or []))
        locations = ", ".join(c.get("name", "") for c in (it.get("location_credits") or []))
        story_arcs = ", ".join(c.get("name", "") for c in (it.get("story_arc_credits") or []))

        volume = it.get("volume") or {}

        return {
            "source_url": it.get("site_detail_url") if "site_detail_url" in it else None,
            "source_scraper": "ComicVine",
            "series": volume.get("name", ""),
            "title": it.get("name") or "",
            "number": it.get("issue_number", ""),
            "summary": re.sub(r"<[^>]+>", " ", it.get("description") or "").strip(),
            "year": year, "month": month, "day": day,
            "writer": ", ".join(dict.fromkeys(credits_by_role["writer"])),
            "penciller": ", ".join(dict.fromkeys(credits_by_role["penciller"])),
            "inker": ", ".join(dict.fromkeys(credits_by_role["inker"])),
            "colorist": ", ".join(dict.fromkeys(credits_by_role["colorist"])),
            "letterer": ", ".join(dict.fromkeys(credits_by_role["letterer"])),
            "cover_artist": ", ".join(dict.fromkeys(credits_by_role["cover_artist"])),
            "editor": ", ".join(dict.fromkeys(credits_by_role["editor"])),
            "characters": characters,
            "teams": teams,
            "locations": locations,
            "story_arc": story_arcs,
            "cover_url": (it.get("image") or {}).get("original_url") or (it.get("image") or {}).get("small_url"),
            "language": "es",
        }
