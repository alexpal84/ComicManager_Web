import os
from pathlib import Path

# --- Rutas base (todas montables como volúmenes Docker) ---
DATA_DIR = Path(os.environ.get("COMICMGR_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "comicmanager.db"
COVERS_DIR = DATA_DIR / "covers"
BACKUPS_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"

for d in (DATA_DIR, COVERS_DIR, BACKUPS_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --- Autenticación básica (single-user, uso personal) ---
AUTH_USER = os.environ.get("COMICMGR_USER", "alex")
AUTH_PASS = os.environ.get("COMICMGR_PASS", "change-me")

# --- ComicVine ---
COMICVINE_API_KEY = os.environ.get("COMICVINE_API_KEY", "")
COMICVINE_BASE_URL = "https://comicvine.gamespot.com/api"

# --- Whakoom (scraper propio, sin API oficial) ---
WHAKOOM_BASE_URL = "https://www.whakoom.com"
# Whakoom exige una sesión autenticada incluso para buscar. Las credenciales
# se inyectan por variables de entorno y nunca se guardan en el repositorio.
WHAKOOM_USER = os.environ.get("WHAKOOM_USER", "")
WHAKOOM_PASS = os.environ.get("WHAKOOM_PASS", "")
WHAKOOM_SESSION_FILE = DATA_DIR / "whakoom-cookies.txt"

# --- Comportamiento de conversión / escritura ---
# Si True, al convertir CBR->CBZ se elimina el .cbr original solo tras verificar
# que el .cbz nuevo se ha creado correctamente y contiene el mismo nº de páginas.
DELETE_ORIGINAL_AFTER_CONVERT = os.environ.get("COMICMGR_DELETE_CBR_AFTER_CONVERT", "true").lower() == "true"

# Formatos de archivo de cómic soportados al escanear
SUPPORTED_EXTENSIONS = {".cbz", ".cbr", ".cb7", ".zip", ".rar"}
INCOMING_ALLOWED_ROOTS = tuple(p for p in os.environ.get("COMICMGR_INCOMING_ALLOWED_ROOTS", "/incoming").split(":") if p)
AUTOMATION_SCAN_SECONDS = max(5, int(os.environ.get("COMICMGR_AUTOMATION_SCAN_SECONDS", "15")))
AUTOMATION_STABLE_SECONDS = max(5, int(os.environ.get("COMICMGR_AUTOMATION_STABLE_SECONDS", "30")))

# Tamaño máximo del lado largo de las miniaturas de portada (px)
THUMBNAIL_MAX_SIDE = 480
