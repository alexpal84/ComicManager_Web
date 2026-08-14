"""Deterministic filename metadata suggestions."""
import re
from datetime import date
from pathlib import Path

RELEASE_TAGS = re.compile(r"\b(?:c2c|ctc|digital|scan|webrip|fixed|repack|noads|\d+p)\b", re.I)
FORMAT_TAGS = [(r"\b(?:annual|anual)\b", "Annual"), (r"\bone[ -]?shot\b", "One-Shot"),
               (r"\b(?:special|especial)\b", "Special"), (r"\bpreview\b", "Preview"),
               (r"\bdirector['’]?s cut\b", "Director's Cut"), (r"\bgiant[ -]?size\b", "Giant-Size")]

def _clean(value):
    value = value.replace("_", " ")
    value = re.sub(r"\.(?=[^\d]|$)", " ", value)
    value = re.sub(r"\[[^]]*\]", " ", value)
    value = re.sub(r"\((?!(?:19|20)\d{2}\))[^)]*\)", " ", value)
    value = RELEASE_TAGS.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip(" -_.")

def parse_comic_filename(file_path: str) -> dict:
    path, text, result = Path(file_path), _clean(Path(file_path).stem), {}
    years = [int(x) for x in re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)]
    valid = [y for y in years if 1900 <= y <= date.today().year + 1]
    if valid:
        result["year"] = valid[-1]
        text = re.sub(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", " ", text)
        text = re.sub(r"\(\s*\)", " ", text)
    volume = re.search(r"\b(?:v(?:ol(?:ume)?\.?)?|volume)\s*(\d+)\b", text, re.I)
    if volume:
        result["volume"] = int(volume.group(1)); text = text[:volume.start()] + " " + text[volume.end():]
    number_re = re.compile(r"(?:#|issue\s*|num\s*|n[ºo]\.?\s*|ch\s*|c\s*|tomo\s*|tome\s*)(\d+(?:\.\d+)?[A-Za-z]?|\d+[A-Za-z])|(?<![\w.])(\d{1,4}(?:\.\d+)?[A-Za-z]?)(?![\w])", re.I)
    candidates = list(number_re.finditer(text))
    if candidates:
        match = candidates[-1]; raw = next(g for g in match.groups() if g is not None)
        if not (raw.isdigit() and len(raw) == 4 and 1900 <= int(raw) <= date.today().year + 1):
            result["number"] = str(int(raw)) if raw.isdigit() else raw
            after = text[match.end():]
            tail = re.sub(r"^[\s–—:-]+", "", after).strip()
            if tail and re.search(r"[A-Za-z0-9]", tail): result["title"] = tail
            text = text[:match.start()]
    for pattern, label in FORMAT_TAGS:
        if re.search(pattern, text, re.I):
            result["format"] = label; text = re.sub(pattern, " ", text, flags=re.I); break
    result["series"] = re.sub(r"\s+", " ", text).strip(" -_.") or _clean(path.parent.name)
    return {k: v for k, v in result.items() if v not in (None, "")}
