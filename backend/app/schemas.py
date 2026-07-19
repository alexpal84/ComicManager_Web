from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class LibraryCreate(BaseModel):
    name: str
    root_path: str


class LibraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    root_path: str
    created_at: datetime
    last_scan_at: Optional[datetime] = None
    comic_count: int = 0


COMIC_EDITABLE_FIELDS = [
    "series", "series_sort", "number", "volume", "title", "count",
    "year", "month", "day", "publisher", "imprint", "format_tag", "language",
    "genre", "web", "manga", "black_and_white", "age_rating",
    "writer", "penciller", "inker", "colorist", "letterer", "cover_artist", "editor",
    "summary", "notes", "characters", "teams", "locations", "story_arc",
    "series_group", "tags", "community_rating", "read", "last_page_read", "rating",
]


class ComicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    library_id: int
    path: str
    filename: str
    format: str
    file_size: int
    page_count: int
    series: str
    series_sort: str
    number: str
    volume: str
    title: str
    count: Optional[int] = None
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    publisher: str
    imprint: str
    format_tag: str
    language: str
    genre: str
    web: str
    manga: str
    black_and_white: str
    age_rating: str
    writer: str
    penciller: str
    inker: str
    colorist: str
    letterer: str
    cover_artist: str
    editor: str
    summary: str
    notes: str
    characters: str
    teams: str
    locations: str
    story_arc: str
    series_group: str
    tags: str
    community_rating: Optional[float] = None
    read: bool
    last_page_read: int
    rating: Optional[int] = None
    cover_thumbnail: Optional[str] = None
    added_at: datetime
    updated_at: datetime
    comicinfo_synced_at: Optional[datetime] = None
    source_scraper: Optional[str] = None
    source_url: Optional[str] = None
    crce_book_id: Optional[str] = None


class ComicUpdate(BaseModel):
    """Todos los campos opcionales: solo se aplican los que vengan informados."""
    series: Optional[str] = None
    series_sort: Optional[str] = None
    number: Optional[str] = None
    volume: Optional[str] = None
    title: Optional[str] = None
    count: Optional[int] = None
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    publisher: Optional[str] = None
    imprint: Optional[str] = None
    format_tag: Optional[str] = None
    language: Optional[str] = None
    genre: Optional[str] = None
    web: Optional[str] = None
    manga: Optional[str] = None
    black_and_white: Optional[str] = None
    age_rating: Optional[str] = None
    writer: Optional[str] = None
    penciller: Optional[str] = None
    inker: Optional[str] = None
    colorist: Optional[str] = None
    letterer: Optional[str] = None
    cover_artist: Optional[str] = None
    editor: Optional[str] = None
    summary: Optional[str] = None
    notes: Optional[str] = None
    characters: Optional[str] = None
    teams: Optional[str] = None
    locations: Optional[str] = None
    story_arc: Optional[str] = None
    series_group: Optional[str] = None
    tags: Optional[str] = None
    community_rating: Optional[float] = None
    read: Optional[bool] = None
    last_page_read: Optional[int] = None
    rating: Optional[int] = None
    write_comicinfo: bool = False   # si True, además de la BBDD escribe el ComicInfo.xml dentro del archivo


class BulkEditRequest(BaseModel):
    comic_ids: List[int]
    changes: ComicUpdate


class MoveRequest(BaseModel):
    comic_id: int
    new_relative_path: str  # relativo a la raíz de la biblioteca del cómic


class RenamePatternRequest(BaseModel):
    comic_ids: List[int]
    pattern: str  # p.ej. "{publisher}/{series}/{series} #{number} ({year})"
    dry_run: bool = True


class ConvertRequest(BaseModel):
    comic_id: int
    delete_original: Optional[bool] = None  # si None, usa el valor por defecto de config


class ScraperSearchRequest(BaseModel):
    scraper: str  # "whakoom" | "comicvine"
    query: str


class ScraperApplyRequest(BaseModel):
    comic_id: int
    scraper: str
    ref: str  # url (whakoom) o issue id (comicvine)
    write_comicinfo: bool = False


class ScraperBulkApplyRequest(BaseModel):
    comic_ids: List[int]
    scraper: str
    series_ref: str
    write_comicinfo: bool = False
    dry_run: bool = True
