from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import init_db
from .routers import libraries, scan, comics, convert, reader, scrapers, comicrackce, automation
from .automation import start_worker

app = FastAPI(title="Comic Manager", version="0.1.0")

init_db()

app.include_router(libraries.router)
app.include_router(scan.router)
app.include_router(comics.router)
app.include_router(convert.router)
app.include_router(reader.router)
app.include_router(scrapers.router)
app.include_router(comicrackce.router)
app.include_router(automation.router)

@app.on_event("startup")
def start_automation():
    start_worker()

app.mount("/static", StaticFiles(directory="/frontend"), name="static")


@app.get("/")
def index():
    return FileResponse("/frontend/index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}
