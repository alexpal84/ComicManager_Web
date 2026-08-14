import datetime as dt

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


class Library(Base):
    """Una biblioteca = una carpeta raíz física con cómics."""
    __tablename__ = "libraries"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    root_path = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    last_scan_at = Column(DateTime, nullable=True)

    comics = relationship("Comic", back_populates="library", cascade="all, delete-orphan")


class Comic(Base):
    """
    Un fichero de cómic (cbz/cbr/...) y sus metadatos.
    Los nombres de campo siguen, en la medida de lo posible, el estándar
    ComicInfo.xml (https://anansi-project.github.io/docs/comicinfo/documentation)
    para que la exportación/importación sea directa.
    """
    __tablename__ = "comics"
    __table_args__ = (UniqueConstraint("library_id", "path", name="uq_library_path"),)

    id = Column(Integer, primary_key=True)
    library_id = Column(Integer, ForeignKey("libraries.id"), nullable=False)
    library = relationship("Library", back_populates="comics")

    # --- Fichero físico ---
    path = Column(String, nullable=False)              # ruta absoluta actual
    filename = Column(String, nullable=False)
    format = Column(String, nullable=False, default="cbz")  # cbz/cbr/cb7
    file_size = Column(Integer, default=0)
    file_mtime = Column(Float, default=0.0)             # para detectar cambios al reescanear
    page_count = Column(Integer, default=0)
    content_hash = Column(String, nullable=True, index=True)

    # --- Identificación ---
    series = Column(String, index=True, default="")
    series_sort = Column(String, index=True, default="")
    number = Column(String, index=True, default="")     # texto: admite "1", "1.5", "Annual 1"...
    volume = Column(String, default="")
    title = Column(String, default="")
    count = Column(Integer, nullable=True)               # nº total de números de la serie

    # --- Publicación ---
    year = Column(Integer, nullable=True)
    month = Column(Integer, nullable=True)
    day = Column(Integer, nullable=True)
    publisher = Column(String, index=True, default="")
    imprint = Column(String, default="")
    format_tag = Column(String, default="")              # ComicInfo "Format" (TPB, Annual, etc.)
    language = Column(String, default="es")
    genre = Column(String, default="")                   # separado por comas
    web = Column(String, default="")
    manga = Column(String, default="Unknown")             # Unknown/Yes/No/YesAndRightToLeft
    black_and_white = Column(String, default="Unknown")   # Unknown/Yes/No
    age_rating = Column(String, default="")

    # --- Créditos ---
    writer = Column(String, default="")
    penciller = Column(String, default="")
    inker = Column(String, default="")
    colorist = Column(String, default="")
    letterer = Column(String, default="")
    cover_artist = Column(String, default="")
    editor = Column(String, default="")

    # --- Contenido ---
    summary = Column(Text, default="")
    notes = Column(Text, default="")
    characters = Column(Text, default="")
    teams = Column(Text, default="")
    locations = Column(Text, default="")
    story_arc = Column(String, default="")
    series_group = Column(String, default="")
    tags = Column(Text, default="")
    community_rating = Column(Float, nullable=True)

    # --- Estado de lectura (equivalente a lo que gestiona ComicRack) ---
    read = Column(Boolean, default=False)
    last_page_read = Column(Integer, default=0)
    rating = Column(Integer, nullable=True)  # 1-5, valoración propia

    # --- Portada / thumbs ---
    cover_thumbnail = Column(String, nullable=True)  # ruta relativa en /data/covers

    # --- Trazabilidad ---
    added_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)
    comicinfo_synced_at = Column(DateTime, nullable=True)  # última vez que se escribió ComicInfo.xml
    comicinfo_written = Column(Boolean, default=False, nullable=False)
    metadata_dirty = Column(Boolean, default=False, nullable=False)
    operation_status = Column(String, nullable=False, default="idle")
    operation_error = Column(Text, nullable=True)
    source_scraper = Column(String, nullable=True)   # "Whakoom" / "ComicVine" / manual
    source_url = Column(String, nullable=True)

    # --- Origen ComicRackCE (para cuando se importe el ComicDb.xml maestro) ---
    crce_book_id = Column(String, nullable=True, index=True)  # Id interno del libro en ComicDb.xml
    crce_imported_at = Column(DateTime, nullable=True)

    @property
    def suggested_metadata(self):
        from .filename_parser import parse_comic_filename
        return parse_comic_filename(self.path or self.filename or "")


class AutomationSettings(Base):
    """Singleton persisted with the same SQLite database as the library."""
    __tablename__ = "automation_settings"
    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, nullable=False)
    incoming_path = Column(String, default="/incoming", nullable=False)
    target_library_id = Column(Integer, ForeignKey("libraries.id"), nullable=True)
    accept_suggestions = Column(Boolean, default=True, nullable=False)
    convert = Column(Boolean, default=True, nullable=False)
    scrape = Column(Boolean, default=True, nullable=False)
    write_comicinfo = Column(Boolean, default=False, nullable=False)
    move = Column(Boolean, default=False, nullable=False)
    move_only_safe = Column(Boolean, default=True, nullable=False)
    use_ai = Column(Boolean, default=False, nullable=False)
    destination_pattern = Column(String, default="{publisher}/{series}/{series} #{number} ({year})", nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class IncomingComic(Base):
    __tablename__ = "incoming_comics"
    id = Column(Integer, primary_key=True)
    source_path = Column(String, nullable=False, unique=True, index=True)
    source_filename = Column(String, nullable=False)
    file_size = Column(Integer, default=0)
    file_mtime = Column(Float, default=0.0)
    stable_since = Column(DateTime, nullable=True)
    comic_id = Column(Integer, ForeignKey("comics.id"), nullable=True)
    status = Column(String, default="Nuevo", nullable=False, index=True)
    last_step = Column(String, default="detectado", nullable=False)
    error = Column(Text, nullable=True)
    candidates_json = Column(Text, default="[]", nullable=False)
    selected_candidate_json = Column(Text, nullable=True)
    selected_manually = Column(Boolean, default=False, nullable=False)
    planned_destination = Column(String, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)
    comic = relationship("Comic")
