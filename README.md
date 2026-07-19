# Comic Manager

Aplicación web personal, ligera, para gestionar tu colección de cómics
(15.000+) desde el navegador: metadatos, portadas, conversión CBR→CBZ,
edición individual y masiva, scrapers de Whakoom y ComicVine, y movimiento
de ficheros. Pensada para convivir con tu instalación de **ComicRack
Community Edition** sin romper nada.

---

## 0. Antes de nada: qué SÍ y qué NO hace hoy esta app

**Hace hoy:**
- Escanea una o varias carpetas ("bibliotecas") y crea **su propia base de
  datos** (SQLite, en `/data/comicmanager.db`), independiente del
  `ComicDb.xml` de ComicRackCE.
- Lee y escribe `ComicInfo.xml` dentro de los `.cbz` (estándar que
  ComicRackCE también usa y respeta).
- Convierte `.cbr` → `.cbz` con el `unrar` oficial, verifica el número de
  páginas y solo entonces borra el original. Conserva además una copia en
  `/data/backups/`.
- Edición individual y masiva de metadatos.
- Scraper de **Whakoom** (tu propio código, portado) y de **ComicVine**
  (API oficial, necesitas tu API key gratuita).
- Mover/renombrar cómics en disco con patrones (`{series}/{series} #{number} ({year})`).
- Lector básico de páginas (para revisar rápido un cómic sin descargarlo).
- Copia de seguridad automática de cualquier fichero antes de tocarlo.

**Todavía NO hace (por lo explicado en el punto 4):**
- **No importa aún tu `ComicDb.xml` real.** Como no hemos podido acceder a
  él durante el desarrollo (estaba en tu PC, sin acceso remoto), lo que
  hay es un **importador de solo lectura** ya construido y a la espera de
  que subas el fichero para ajustarlo a la estructura exacta de tu
  ComicRackCE y probarlo. Ver sección 4.
- No escribe de vuelta en el `ComicDb.xml` de forma automática (hay una
  función experimental para ello, pero requiere validación manual primero,
  ver sección 4.4).

---

## 1. Instalación en tu servidor Debian

### 1.1 Requisitos
- Docker y Docker Compose instalados en el servidor Debian.
- Acceso a la carpeta donde están físicamente tus cómics.

### 1.2 Pasos

```bash
# 1. Copia toda la carpeta "comicmanager" a tu servidor, por ejemplo:
scp -r comicmanager/ usuario@tu-servidor:/opt/comicmanager

# 2. Entra al servidor y a la carpeta
ssh usuario@tu-servidor
cd /opt/comicmanager

# 3. Edita docker-compose.yml:
#    - Cambia la ruta "/ruta/a/tu/coleccion" por la ruta REAL donde
#      están tus cómics en el servidor (la misma que ya usan
#      Kavita/Komga/YACReaderLibraryServer, si es la misma colección).
#    - Opcionalmente pon tu API key de ComicVine.
nano docker-compose.yml

# 4. Construye y levanta el contenedor
docker compose up -d --build

# 5. Comprueba que está arriba
docker compose logs -f
```

Accede desde el navegador a `http://IP-DE-TU-SERVIDOR:8000`.
Define `COMICMGR_USER` y `COMICMGR_PASS` en tu archivo `.env` antes de
arrancar. El archivo está excluido de Git para que las credenciales no se
publiquen.

> Para acceso remoto seguro desde fuera de casa, te recomiendo poner esta
> app detrás de tu reverse proxy habitual (el mismo que uses para Kavita/
> Komga) con HTTPS, en vez de exponer el puerto 8000 directamente a
> internet. La autenticación básica incluida es una capa mínima, pensada
> para uso personal, no para exposición pública sin más protección.

### 1.3 Primeros pasos dentro de la app
1. Entra con tu usuario/contraseña.
2. Pulsa **"Bibliotecas"** → añade una biblioteca nueva indicando la ruta
   **dentro del contenedor** (la de la derecha del `:` en el volumen, p.ej.
   `/comics` si montaste `/ruta/a/tu/coleccion:/comics`).
3. Selecciona esa biblioteca en el desplegable superior y pulsa
   **"Escanear"**. Para 15.000 cómics, la primera vez puede tardar bastante
   (generar miniaturas de portada uno a uno) — puedes seguir el progreso en
   la barra que aparece bajo la cabecera y seguir navegando mientras tanto.

---

## 2. Uso diario

- **Ver/editar un cómic**: haz clic en su portada. Se abre un panel con
  todos los campos, resumen, botón de lectura, conversión (si es cbr) y
  búsqueda de metadatos.
- **Selección múltiple**: marca varios cómics para convertir CBR→CBZ,
  completar metadatos, escribir ComicInfo o mover/renombrar en lote.
- **Scraper por serie**: selecciona varios cómics de una misma serie,
  busca la colección en Whakoom o ComicVine y revisa la previsualización.
  La app empareja cada archivo con su número antes de aplicar los metadatos;
  los ejemplares sin coincidencia quedan intactos y aparecen en el informe.
- **Vistas de biblioteca**: cambia entre portadas, miniaturas, detalle y
  listado. La densidad, el tamaño de página (30–500), el campo de orden y
  su sentido se guardan en el navegador.
- **Vistas inteligentes**: incluye "CBR por convertir", "Metadatos mínimos
  incompletos" (serie, guionista o tags), "Modificados sin sincronizar",
  "Sin ComicInfo" y otros filtros de revisión.
- **Editar en lote**: marca solo las casillas de los campos que quieres
  sobrescribir en todos los seleccionados (el resto no se toca).
- **Mover/renombrar en lote**: define un patrón de carpetas, previsualiza
  el resultado, y aplica. Mueve el fichero físico y actualiza la ruta en
  la base de datos de esta app.
- **Convertir CBR→CBZ**: disponible individualmente y por lotes. El CBR se
  elimina únicamente después de comprobar que el CBZ contiene el mismo
  número de páginas; antes se guarda una copia de seguridad.
- **Escribir ComicInfo.xml**: disponible al guardar y como operación por
  lotes. Al completarse limpia el estado "modificado sin sincronizar".

---

## 3. Copias de seguridad

Antes de **cualquier** operación que modifique un fichero existente
(escritura de ComicInfo.xml, conversión CBR→CBZ, importación desde
ComicDb.xml), la app copia el fichero original a `/data/backups/` con un
timestamp, y nunca sobreescribe backups anteriores. Puedes revisar esa
carpeta en cualquier momento:

```bash
ls -la /opt/comicmanager/data/backups/
```

Para restaurar, simplemente copia el backup de vuelta a su ubicación
original (fuera de esta app, con `cp`).

La propia base de datos de esta app (`/data/comicmanager.db`) también
puedes respaldarla tú periódicamente con un simple `cp`, ya que es un
único fichero SQLite.

---

## 4. Integración con ComicRackCE / tu `ComicDb.xml`

### 4.1 Por qué está en "modo preparado, pendiente de validar"
No tuvimos acceso a tu `ComicDb.xml` real durante el desarrollo. El
formato de ComicRack(CE) es un único XML con un nodo por libro, pero los
nombres exactos de los campos (atributos vs. sub-nodos, nombres como
`FilePath` vs `Path`, etc.) pueden variar ligeramente entre versiones. El
importador que hemos construido (`backend/app/comicrackce/importer.py`)
**contempla varios alias por campo**, pero hay que confirmarlo contra tu
fichero real.

### 4.2 Cuando vuelvas a casa y tengas acceso al `ComicDb.xml`

```bash
# 1. Copia el ComicDb.xml (o una COPIA de él, nunca el original en uso)
#    a la carpeta que ya está montada como volumen:
cp /ruta/en/tu/pc/ComicDb.xml /opt/comicmanager/comicrackce-import/

# 2. Inspecciona su estructura real (solo lectura, no modifica nada):
curl -u "$COMICMGR_USER:$COMICMGR_PASS" \
  "http://localhost:8000/api/comicrackce/inspect?xml_path=/comicrackce-import/ComicDb.xml"
```

Esto te devuelve un resumen de qué tags existen y con qué frecuencia. Si
los nombres no coinciden con lo que espera `FIELD_ALIASES` en
`importer.py`, hay que ajustar esa tabla (pídemelo y lo hago en cuanto
tengamos el fichero real, o edítala tú mismo siguiendo los comentarios del
propio fichero).

```bash
# 3. Informe de qué importaría, SIN tocar nuestra base de datos:
curl -u "$COMICMGR_USER:$COMICMGR_PASS" \
  "http://localhost:8000/api/comicrackce/dry-run?xml_path=/comicrackce-import/ComicDb.xml"

# 4. Si el informe tiene sentido (nº de coincidencias razonable), aplica
#    la importación a NUESTRA base de datos (nunca toca el ComicDb.xml):
curl -u "$COMICMGR_USER:$COMICMGR_PASS" -X POST \
  "http://localhost:8000/api/comicrackce/import?xml_path=/comicrackce-import/ComicDb.xml&match_by=path"
```

La importación **solo rellena campos que estén vacíos** en nuestra base
de datos — no pisa nada que ya hayas editado desde esta app.

### 4.3 Qué pasa con las rutas de fichero
Como tu `ComicDb.xml` fue creado con ComicRack corriendo en Windows, las
rutas de fichero probablemente sean del tipo `D:\Comics\Serie\...cbr`. El
emparejamiento automático por ruta exacta no funcionará en ese caso;
usa `match_by=filename` (empareja por nombre de fichero, más laxo — solo
si el nombre es único en toda tu colección) o dime el patrón de tus rutas
Windows y ajusto el emparejador para traducirlas a las rutas Linux
correspondientes.

### 4.4 Escritura de vuelta en ComicDb.xml (experimental, desactivada por defecto)
Existe un módulo (`backend/app/comicrackce/exporter.py`) capaz de
actualizar **solo la ruta del fichero** de los libros que muevas desde
esta app, para mantener sincronizado tu ComicDb.xml si sigues usando
ComicRack en el PC. Está en modo "solo genera una copia modificada para
que la revises" hasta que confirmemos juntos la estructura real de tu
fichero — no lo activaremos sobre el original sin que antes lo pruebes
abriendo la copia modificada en ComicRack.

---

## 5. Los scrapers

### 5.1 Whakoom
Es un **puerto a Python 3** de tu propio plugin
(`alexpal84/ComicRack-Scraper-ES`), con la misma lógica de parseo de HTML
por expresiones regulares, adaptada de IronPython/.NET a Python+requests.
Whakoom exige sesión también para las búsquedas. Define `WHAKOOM_USER` y
`WHAKOOM_PASS` en el entorno de Docker (por ejemplo, en un archivo `.env`, que
ya está excluido de Git); no incluyas las credenciales en este repositorio. Si
Whakoom cambia el HTML de su web en el
futuro, habrá que retocar las expresiones regulares en
`backend/app/scrapers/whakoom.py` (están comentadas y organizadas por
función para facilitarlo). La sesión se conserva en
`/data/whakoom-cookies.txt`: sólo se vuelve a iniciar sesión si esa cookie
caduca o Whakoom responde con un 401.

### 5.2 ComicVine
Usa la API oficial. Necesitas tu propia API key gratuita:
1. Crea una cuenta en https://comicvine.gamespot.com/
2. Ve a https://comicvine.gamespot.com/api/ y copia tu API key.
3. Ponla en `docker-compose.yml`, variable `COMICVINE_API_KEY`, y
   reinicia el contenedor (`docker compose up -d`).

No se ha reutilizado el binario `.NET` del plugin original de
ComicRackCE (no es viable cargarlo desde un backend Python), pero el
resultado funcional es equivalente: búsqueda de la serie → lista de
números → aplicar metadatos + portada.

---

## 6. Sinergias con Kavita / Komga / YACReaderLibraryServer

Todas esas apps también leen `ComicInfo.xml` embebido en los cbz como
fuente de metadatos, así que **cualquier metadato que edites o
scrapees desde esta app y marques "escribir en ComicInfo.xml" se verá
reflejado automáticamente la próxima vez que Kavita/Komga/YACReader
re-escaneen esas carpetas** — no hace falta duplicar el trabajo de
catalogación en cada aplicación por separado. Recomendación práctica:
usa Comic Manager como la herramienta de catalogación/edición "maestra",
y las otras como visores/lectores del resultado.

Ten en cuenta que si dos de estas apps escanean la misma carpeta a la vez
que Comic Manager está escribiendo un ComicInfo.xml, en un caso muy raro
podrían leer el fichero a medio escribir. La escritura está implementada
de forma atómica (se genera un `.cbz` temporal completo y solo al final
se sustituye el original), así que el riesgo real es mínimo, pero evita
lanzar escaneos masivos simultáneos en varias apps a la vez sobre la
misma biblioteca.

---

## 7. Limitaciones conocidas

- **RAR5 / cbr con contraseña**: los `.cbr` protegidos con contraseña no
  se pueden procesar (ni ComicRack podía). Los RAR multi-volumen
  (`.part1.rar`, etc.) tampoco están contemplados en esta primera versión.
- **Rendimiento con 15.000 cómics**: el primer escaneo completo (que
  genera todas las miniaturas) es la operación más lenta. Escaneos
  posteriores solo tocan los ficheros nuevos o modificados (se comparan
  tamaño+fecha), así que son mucho más rápidos.
- **Single-user**: no hay gestión de usuarios/roles; es exactamente lo que
  pediste (uso personal), pero si en el futuro quieres compartir acceso
  con más gente habría que añadir un sistema de cuentas real.
- **Whakoom sin API oficial**: si cambian su web, el scraper puede dejar
  de funcionar hasta que se actualicen las expresiones regulares.
- **ComicDb.xml**: como se ha explicado en la sección 4, el importador
  está construido pero pendiente de validar contra tu fichero real.
- **Lector básico**: no sustituye a un lector completo (sin modo doble
  página, sin zoom avanzado, sin soporte PDF). Si lo necesitas, dímelo y
  lo ampliamos.

---

## 8. Estructura del proyecto

```
comicmanager/
├── backend/app/
│   ├── main.py              # FastAPI app, monta routers y frontend
│   ├── config.py            # rutas, credenciales, API keys (vía env vars)
│   ├── models.py            # ORM: Library, Comic (campos ComicInfo.xml)
│   ├── schemas.py           # Pydantic: validación de la API
│   ├── database.py          # conexión SQLite
│   ├── auth.py              # HTTP Basic Auth
│   ├── scanner.py           # escaneo de bibliotecas físicas
│   ├── mover.py             # mover/renombrar con patrones
│   ├── archive_utils.py     # leer cbz/cbr, portadas, convertir, escribir XML
│   ├── comicinfo.py         # serialización ComicInfo.xml
│   ├── backup.py            # copias de seguridad automáticas
│   ├── scrapers/
│   │   ├── whakoom.py       # puerto de tu plugin ComicRack-Scraper-ES
│   │   └── comicvine.py     # API oficial de ComicVine
│   ├── comicrackce/
│   │   ├── importer.py      # lectura de ComicDb.xml (solo lectura)
│   │   └── exporter.py      # escritura experimental (rutas de fichero)
│   └── routers/              # endpoints de la API REST
├── frontend/
│   ├── index.html
│   ├── app.js               # SPA en JS vanilla, sin build step
│   └── styles.css
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 9. Próximos pasos sugeridos (cuando vuelvas a casa)

1. Copia tu `ComicDb.xml` (una copia, no el original en uso) al servidor.
2. Ejecuta `inspect` y `dry-run` (sección 4.2) y compárteme el resultado
   si algo no encaja — lo más probable es que solo haga falta ajustar la
   tabla de alias de campos.
3. Decide el criterio de emparejamiento (`path` si migras las rutas de
   Windows a Linux con la misma estructura relativa, o `filename` si no).
4. Une esa importación con lo que el escaneo físico ya habrá detectado.
