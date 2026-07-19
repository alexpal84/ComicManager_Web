from .whakoom import WhakoomScraper
from .comicvine import ComicVineScraper

SCRAPERS = {
    "whakoom": WhakoomScraper,
    "comicvine": ComicVineScraper,
}


def get_scraper(name: str):
    cls = SCRAPERS.get(name)
    if not cls:
        raise ValueError(f"Scraper desconocido: {name}")
    return cls()
