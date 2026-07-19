FROM python:3.12-slim

# unrar-free: suficiente para arrancar la app en este entorno de prueba.
# Si luego quieres máxima compatibilidad con RAR5, se puede volver a unrar
# real cuando la imagen base y los repositorios estén alineados.
RUN apt-get update \
    && apt-get install -y --no-install-recommends unrar-free libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app /app/app
COPY frontend /frontend

ENV COMICMGR_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app"]
