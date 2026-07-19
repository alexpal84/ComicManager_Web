# -*- coding: utf-8 -*-
"""
Scraper de Whakoom.com — puerto a Python 3 puro (requests) del plugin
original para ComicRack Community Edition (IronPython), del propio autor
del proyecto. La lógica de parseo (expresiones regulares sobre el HTML)
se mantiene igual; solo cambia la capa de red (System.Net -> requests) y
la gestión de cadenas (unicode nativo de Python 3).
"""
from __future__ import annotations
import re
import html
from http.cookiejar import MozillaCookieJar
from typing import List, Dict, Any, Optional

import requests

from .base import BaseScraper
from ..config import (
    WHAKOOM_BASE_URL, WHAKOOM_USER, WHAKOOM_PASS, WHAKOOM_SESSION_FILE,
)


class WhakoomAuthenticationError(RuntimeError):
    """Whakoom no permite buscar sin una sesión iniciada."""


class WhakoomScraper(BaseScraper):
    name = "whakoom"

    def __init__(self):
        self.base_url = WHAKOOM_BASE_URL
        self.session = requests.Session()
        self._cookie_jar = MozillaCookieJar(str(WHAKOOM_SESSION_FILE))
        try:
            self._cookie_jar.load(ignore_discard=True, ignore_expires=True)
        except (FileNotFoundError, OSError, ValueError):
            pass
        self.session.cookies = self._cookie_jar
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        })
        self._current_series_roles: Dict[str, str] = {}

    def _save_session(self) -> None:
        try:
            self._cookie_jar.save(ignore_discard=True, ignore_expires=True)
        except OSError:
            # No impedimos la búsqueda si el volumen /data no estuviera disponible.
            pass

    # ---------- utilidades de parseo (idénticas al plugin original) ----------

    def _decode(self, text: Optional[str]) -> str:
        if text is None:
            return ""
        return html.unescape(text).replace("\xa0", " ")

    def _strip_tags(self, text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text or "")

    def _clean_text(self, text: str) -> str:
        text = self._decode(self._strip_tags(text))
        return re.sub(r"\s+", " ", text).strip()

    def _extract_first(self, html_text: str, patterns: List[str],
                        flags=re.IGNORECASE | re.DOTALL, cleaner=True) -> str:
        for pattern in patterns:
            m = re.search(pattern, html_text, flags)
            if m:
                value = m.group(1) if m.lastindex else m.group(0)
                return self._clean_text(value) if cleaner else self._decode(value)
        return ""

    def _normalize_url(self, url: str) -> str:
        url = (url or "").strip()
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if not url.startswith("/"):
            url = "/" + url
        return self.base_url + url

    def _request(self, url, method="GET", data=None, json_body=None,
                 content_type=None, referer=None, extra_headers=None,
                 allow_redirects=True) -> requests.Response:
        headers = {}
        if referer:
            headers["Referer"] = referer
        if content_type:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        resp = self.session.request(method, url, data=data, json=json_body,
                                     headers=headers, timeout=20,
                                     allow_redirects=allow_redirects)
        resp.raise_for_status()
        return resp

    def _login(self) -> None:
        """Reproduce el inicio de sesión previo a la búsqueda del plugin CE."""
        if not WHAKOOM_USER or not WHAKOOM_PASS:
            raise WhakoomAuthenticationError(
                "Configura WHAKOOM_USER y WHAKOOM_PASS en el entorno del contenedor. "
                "Whakoom requiere iniciar sesión para buscar."
            )

        login_url = self.base_url + "/login?ReturnUrl=/"
        login_page = self._request(login_url).text
        verification_token = self._extract_first(
            login_page,
            [r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"'],
            cleaner=False,
        )
        if not verification_token:
            raise WhakoomAuthenticationError("No se pudo obtener el token del formulario de Whakoom.")
        response = self._request(
            login_url,
            method="POST",
            data={
                "username": WHAKOOM_USER,
                "userpassw": WHAKOOM_PASS,
                "remember": "true",
                "__RequestVerificationToken": verification_token,
            },
            content_type="application/x-www-form-urlencoded",
            referer=login_url,
            allow_redirects=False,
        )
        if response.status_code != 302 or response.headers.get("Location") != "/":
            raise WhakoomAuthenticationError("Whakoom rechazó las credenciales configuradas.")
        self._save_session()

    def _extract_search_html(self, json_str: str) -> str:
        idx = json_str.find('"searchResult":"')
        if idx == -1:
            return ""
        raw_html = json_str[idx + 16:].rstrip("}").rstrip('"')
        text = raw_html.replace('\\"', '"').replace("\\/", "/") \
            .replace("\\n", "\n").replace("\\r", "").replace("\\t", "")
        return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)

    def _parse_month(self, name: str) -> int:
        months = {
            "january": 1, "jan": 1, "enero": 1,
            "february": 2, "feb": 2, "febrero": 2,
            "march": 3, "mar": 3, "marzo": 3,
            "april": 4, "apr": 4, "abril": 4,
            "may": 5, "mayo": 5,
            "june": 6, "jun": 6, "junio": 6,
            "july": 7, "jul": 7, "julio": 7,
            "august": 8, "aug": 8, "agosto": 8,
            "september": 9, "sep": 9, "sept": 9, "septiembre": 9,
            "october": 10, "oct": 10, "octubre": 10,
            "november": 11, "nov": 11, "noviembre": 11,
            "december": 12, "dec": 12, "diciembre": 12,
        }
        return months.get((name or "").lower(), 0)

    def _parse_date_text(self, text: str):
        text = self._decode(text).strip()
        if not text:
            return None, None, None
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        m = re.match(r"^(\d{4})$", text)
        if m:
            return int(m.group(1)), None, None
        m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$", text, re.IGNORECASE)
        if m:
            month = self._parse_month(m.group(1))
            if month:
                return int(m.group(3)), month, int(m.group(2))
        m = re.match(r"^([A-Za-z]+)\s+(\d{4})$", text, re.IGNORECASE)
        if m:
            month = self._parse_month(m.group(1))
            if month:
                return int(m.group(2)), month, None
        m = re.match(r"^(\d{1,2})\s+de\s+([A-Za-z]+)\s+de\s+(\d{4})$", text, re.IGNORECASE)
        if m:
            month = self._parse_month(m.group(2))
            if month:
                return int(m.group(3)), month, int(m.group(1))
        m = re.match(r"^([A-Za-z]+)\s+de?\s*(\d{4})$", text, re.IGNORECASE)
        if m:
            month = self._parse_month(m.group(1))
            if month:
                return int(m.group(2)), month, None
        return None, None, None

    def _extract_page_heading(self, html_text: str) -> str:
        title = self._extract_first(html_text, [
            r"<h1[^>]*>(.*?)</h1>",
            r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
            r"<title>(.*?)</title>",
        ])
        title = re.sub(r"\s*\|\s*Whakoom.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*\((?:[^)]*)\)\s*$", "", title)
        return title.strip()

    def _extract_subtitle(self, html_text: str) -> str:
        return self._extract_first(html_text, [
            r'<p[^>]*class="title"[^>]*>(.*?)</p>',
            r'<div[^>]*class="[^"]*subtitle[^"]*"[^>]*>(.*?)</div>',
            r'<meta[^>]+property="og:title"[^>]+content="[^"]*#\d+[\s:\-]+([^"]+)"',
        ])

    def _extract_plot(self, html_text: str) -> str:
        plot = self._extract_first(html_text, [
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
            r'(?:<h[23][^>]*>\s*(?:Plot|Argumento)\s*</h[23]>)(.*?)(?=<h[23]|<div[^>]+class="[^"]*(?:art|reviews|lists)[^"]*")',
        ])
        plot = re.sub(r"\s*(View more|Ver m[aá]s)\s*$", "", plot, flags=re.IGNORECASE)
        if re.match(r"^(Plot unknown|No conocemos el argumento)$", plot, re.IGNORECASE):
            return ""
        return plot

    def _extract_rating(self, html_text: str) -> str:
        rating = self._extract_first(html_text, [
            r'itemprop="ratingValue"[^>]*>\s*([\d\.,]+)\s*<',
            r'"ratingValue"\s*:\s*"([\d\.,]+)"',
        ], cleaner=False)
        return rating.replace(",", ".").strip()

    def _extract_publisher(self, html_text: str) -> str:
        return self._extract_first(html_text, [
            r'itemprop="publisher".*?itemprop="name">([^<]+)</span>',
            r"(?:Spanish|Espa[nñ]ol)[^<]{0,80}[·\xB7]\s*(?:<a[^>]*>)?([^<]+)",
            r"(?:Editorial|Publisher)</h3>\s*<p>(?:<a[^>]*>)?([^<]+)",
        ])

    def _extract_cover(self, html_text: str) -> str:
        return self._extract_first(html_text, [
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"',
        ], cleaner=False)

    def _extract_series_name(self, html_text: str, fallback="") -> str:
        series = self._extract_first(html_text, [
            r'<a[^>]*href="/ediciones/[^"]+"[^>]*>([^<]+)</a>\s*</[^>]+>\s*(?:<div|<section|<h[23])',
            r'<a[^>]*href="/ediciones/[^"]+"[^>]*>([^<]+)</a>',
        ])
        return series or fallback

    def _extract_authors_block(self, html_text: str) -> str:
        return self._extract_first(html_text, [
            r'<div[^>]+class="[^"]*authors[^"]*"[^>]*>(.*?)</div>',
            r'(?:<h[23][^>]*>\s*(?:Authors|Autores)\s*</h[23]>)(.*?)(?=<h[23]|<div[^>]+class="[^"]*(?:lists|reviews|art)[^"]*")',
        ], cleaner=False)

    def _collect_series_roles(self, html_text: str) -> Dict[str, str]:
        roles: Dict[str, str] = {}
        block = self._extract_authors_block(html_text)
        if not block:
            return roles
        for name, raw_roles in re.findall(
                r'<a[^>]*href="/autor(?:es)?/[^"]+"[^>]*>(.*?)</a>(?:(?:\s|&nbsp;|&#160;|,)*\(([^)]+)\))?',
                block, re.IGNORECASE | re.DOTALL):
            author = self._clean_text(name)
            role_text = self._decode(raw_roles).lower().strip() if raw_roles else ""
            if author:
                roles[author] = role_text
        return roles

    def _assign_role(self, auth: dict, role_key: str, name: str):
        if name and name not in auth[role_key]:
            auth[role_key].append(name)

    def _parse_authors(self, html_text: str) -> Dict[str, List[str]]:
        auth = {"writer": [], "penciller": [], "inker": [], "colorist": []}
        block = self._extract_authors_block(html_text)
        if not block:
            return auth
        for name, raw_roles in re.findall(
                r'<a[^>]*href="/autor(?:es)?/[^"]+"[^>]*>(.*?)</a>(?:(?:\s|&nbsp;|&#160;|,)*\(([^)]+)\))?',
                block, re.IGNORECASE | re.DOTALL):
            author = self._clean_text(name)
            role_text = self._decode(raw_roles).lower().strip() if raw_roles else ""
            if not role_text:
                role_text = self._current_series_roles.get(author, "")
            if not author or not role_text:
                continue
            if "guion" in role_text or "script" in role_text or "writer" in role_text:
                self._assign_role(auth, "writer", author)
            if any(k in role_text for k in ("dibujo", "drawing", "pencil", "penciller", "artist")):
                self._assign_role(auth, "penciller", author)
            if "tinta" in role_text or "inker" in role_text:
                self._assign_role(auth, "inker", author)
            if "color" in role_text or "colour" in role_text:
                self._assign_role(auth, "colorist", author)
        return auth

    def _extract_issue_links(self, html_text: str) -> List[Dict[str, str]]:
        items = []
        seen = set()
        for url, text in re.findall(
                r'<a[^>]*href=["\']((?:https?://[^"\']+)?/comics/[^"\']+)["\'][^>]*>(.*?)</a>',
                html_text, re.IGNORECASE | re.DOTALL):
            clean_title = self._clean_text(text)
            if not clean_title or clean_title.lower() == "image":
                continue
            full_url = self._normalize_url(url)
            if full_url in seen:
                continue
            seen.add(full_url)
            number = self._extract_first(clean_title, [r"#\s*(\d+)"], cleaner=False)
            if not number:
                number = self._extract_first(full_url, [r"/(\d+)(?:[#?].*)?$"], cleaner=False)
            if not number:
                number = "1"
            items.append({"url": full_url, "title": clean_title, "number": number})
        return items

    def _sort_issues(self, issues):
        def sort_key(item):
            m = re.search(r"\d+", item.get("number", ""))
            return int(m.group()) if m else 999999
        return sorted(issues, key=sort_key)

    # ---------------------------- API pública ----------------------------

    def search(self, query: str) -> List[Dict[str, Any]]:
        url = self.base_url + "/search.aspx/Query"
        payload = {"q": query, "ft": 0, "fit": "", "fp": "", "fl": "", "p": 1}
        try:
            if not self._cookie_jar:
                self._login()
            response = self._request(
                url, method="POST", json_body=payload,
                content_type="application/json; charset=UTF-8",
                referer=self.base_url + "/",
                extra_headers={"X-Requested-With": "XMLHttpRequest"},
            )
        except requests.RequestException as exc:
            # Una cookie guardada puede caducar. Reintentamos una vez con login;
            # en condiciones normales la cookie persistida evita este paso.
            if getattr(exc.response, "status_code", None) != 401:
                raise RuntimeError(f"No se pudo consultar Whakoom: {exc}") from exc
            try:
                self._login()
                response = self._request(
                    url, method="POST", json_body=payload,
                    content_type="application/json; charset=UTF-8",
                    referer=self.base_url + "/",
                    extra_headers={"X-Requested-With": "XMLHttpRequest"},
                )
            except requests.RequestException as retry_exc:
                raise RuntimeError(f"No se pudo consultar Whakoom: {retry_exc}") from retry_exc

        html_text = self._extract_search_html(response.text)
        results = []
        seen = set()
        for block in re.split(r'<div[^>]+class="[^"]*\bsresult\b[^"]*"', html_text, flags=re.IGNORECASE)[1:]:
            link = self._extract_first(block, [
                r'<p[^>]*class="title"[^>]*>\s*<a[^>]*href="([^"]+)"',
                r'<a[^>]*href="([^"]+)"',
            ], cleaner=False)
            title = self._extract_first(block, [
                r'<p[^>]*class="title"[^>]*>\s*<a[^>]*href="[^"]+"[^>]*>(.*?)</a>',
                r'<p[^>]*class="title"[^>]*>(.*?)</p>',
            ])
            if not link or not title:
                continue
            link = self._normalize_url(link)
            if link in seen:
                continue
            seen.add(link)

            publisher = self._extract_first(block, [
                r'<span[^>]*class="pub"[^>]*>([^<]+)</span>',
            ])
            year = self._extract_first(block, [
                r"\(\s*((?:19|20)\d{2})\s*(?:[-/]\s*(?:19|20)\d{2})?\s*\)",
            ], cleaner=False)

            results.append({
                "ref": link,
                "title": title,
                "series": re.sub(r"#\d+.*$", "", title).strip(),
                "publisher": publisher,
                "year": year.strip() if year else "",
                "source": "Whakoom",
            })
        return results

    def get_series_issues(self, series_url: str) -> List[Dict[str, str]]:
        issues: List[Dict[str, str]] = []
        self._current_series_roles = {}
        try:
            base_url = self._normalize_url(series_url.split("?")[0].rstrip("/"))
            if base_url.endswith("/todos"):
                base_url = base_url[:-6]
            html_main = self._request(base_url).text
            self._current_series_roles = self._collect_series_roles(html_main)
            issues = self._extract_issue_links(html_main)
            if issues:
                return self._sort_issues(issues)
            if "/ediciones/" in base_url:
                page = 1
                seen = set()
                while True:
                    current_url = base_url + "/todos" + (f"?page={page}" if page > 1 else "")
                    try:
                        html_page = self._request(current_url).text
                    except requests.RequestException:
                        break
                    page_items = self._extract_issue_links(html_page)
                    added = 0
                    for item in page_items:
                        if item["url"] in seen:
                            continue
                        seen.add(item["url"])
                        issues.append(item)
                        added += 1
                    if added == 0:
                        break
                    page += 1
            return self._sort_issues(issues) if issues else [
                {"url": base_url, "title": self._extract_page_heading(html_main), "number": "1"}
            ]
        except Exception:
            return issues

    def get_details(self, ref: str) -> Dict[str, Any]:
        url = self._normalize_url(ref)
        html_text = self._request(url).text

        heading = self._extract_page_heading(html_text)
        subtitle = self._extract_subtitle(html_text)
        publisher = self._extract_publisher(html_text)
        plot = self._extract_plot(html_text)
        authors = self._parse_authors(html_text)
        cover = self._extract_cover(html_text)
        rating = self._extract_rating(html_text)
        series_name = self._extract_series_name(html_text, fallback=heading)

        raw_date = self._extract_first(html_text, [
            r'itemprop="datePublished"\s+content="([^"]+)"',
            r'"datePublished"\s*:\s*"([^"]+)"',
        ])
        year, month, day = self._parse_date_text(raw_date)

        title = subtitle or self._extract_first(heading, [r"#\s*\d+\s+(.+)$"]) or heading
        number = self._extract_first(heading, [r"#\s*(\d+)"], cleaner=False) or ""

        return {
            "source_url": url,
            "source_scraper": "Whakoom",
            "series": series_name,
            "title": title,
            "number": number,
            "publisher": publisher,
            "writer": ", ".join(authors["writer"]),
            "penciller": ", ".join(authors["penciller"]),
            "inker": ", ".join(authors["inker"]),
            "colorist": ", ".join(authors["colorist"]),
            "community_rating": float(rating) if rating else None,
            "year": year, "month": month, "day": day,
            "summary": plot,
            "cover_url": self._normalize_url(cover) if cover else None,
            "language": "es",
        }
