// ===================== Estado y autenticación =====================
const STORAGE_KEYS = {
  auth: "cm_auth",
  user: "cm_user",
  pass: "cm_pass",
  preferences: "cm_preferences",
};

const savedPreferences = JSON.parse(localStorage.getItem(STORAGE_KEYS.preferences) || "{}");

const state = {
  authHeader: localStorage.getItem(STORAGE_KEYS.auth) || null,
  libraries: [],
  currentLibraryId: null,
  comics: [],
  offset: 0,
  limit: Number(savedPreferences.limit) || 60,
  viewMode: savedPreferences.viewMode || "grid",
  selection: new Set(),
  filters: { q: "", sort: savedPreferences.sort || "series", order: savedPreferences.order || "asc", view: "all", missing: "" },
};

const SMART_VIEWS = {
  all: {}, unread: { unread_only: true }, identity: { missing: "series,number" },
  publication: { missing: "year,publisher" }, credits: { missing: "writer,penciller" },
  summary: { missing: "summary" }, cover: { missing: "cover" }, comicinfo: { missing: "comicinfo" },
};

// Se declara antes de cualquier arranque asíncrono. De este modo, una sesión
// restaurada nunca puede abrir el detalle mientras la configuración está en TDZ.
const EDITABLE_FIELDS = Object.freeze([
  ["series", "Serie"], ["number", "Número"], ["volume", "Volumen"], ["title", "Título"],
  ["year", "Año"], ["month", "Mes"], ["day", "Día"], ["publisher", "Editorial"],
  ["genre", "Género"], ["language", "Idioma"], ["writer", "Guionista"], ["penciller", "Dibujante"],
  ["inker", "Entintador"], ["colorist", "Colorista"], ["letterer", "Rotulista"],
  ["cover_artist", "Portadista"], ["editor", "Editor"], ["story_arc", "Saga"],
  ["characters", "Personajes"], ["teams", "Equipos"], ["locations", "Localizaciones"],
  ["tags", "Etiquetas"],
]);

function savePreferences() {
  localStorage.setItem(STORAGE_KEYS.preferences, JSON.stringify({
    limit: state.limit, viewMode: state.viewMode, sort: state.filters.sort, order: state.filters.order,
  }));
}

function basicAuthHeader(user, pass) {
  const raw = `${user.trim()}:${pass.trim()}`;
  const bytes = new TextEncoder().encode(raw);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return "Basic " + btoa(binary);
}

function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.authHeader) headers["Authorization"] = state.authHeader;
  return fetch(path, { ...options, headers }).then(async (resp) => {
    if (resp.status === 401) {
      state.authHeader = null;
      localStorage.removeItem(STORAGE_KEYS.auth);
      showLogin("Credenciales incorrectas.", "error");
      throw new Error("No autorizado");
    }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Error de servidor");
    }
    const ct = resp.headers.get("content-type") || "";
    return ct.includes("application/json") ? resp.json() : resp;
  });
}

function setLoginStatus(message = "", kind = "error") {
  const el = document.getElementById("login-status");
  el.textContent = message;
  el.className = `login-status ${kind} ${message ? "" : "hidden"}`.trim();
}

function showLogin(message = "", kind = "error") {
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("app").classList.add("hidden");
  setLoginStatus(message, kind);
}

function hideLogin() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
}

function fillSavedCredentials() {
  document.getElementById("login-user").value = localStorage.getItem(STORAGE_KEYS.user) || "";
  document.getElementById("login-pass").value = localStorage.getItem(STORAGE_KEYS.pass) || "";
  document.getElementById("login-remember").checked = Boolean(localStorage.getItem(STORAGE_KEYS.user) || localStorage.getItem(STORAGE_KEYS.pass));
}

function saveCredentials(user, pass, remember) {
  if (remember) {
    localStorage.setItem(STORAGE_KEYS.user, user);
    localStorage.setItem(STORAGE_KEYS.pass, pass);
  } else {
    localStorage.removeItem(STORAGE_KEYS.user);
    localStorage.removeItem(STORAGE_KEYS.pass);
  }
}

async function loginWithCredentials(user, pass, remember) {
  const header = basicAuthHeader(user, pass);
  const resp = await fetch("/api/libraries", { headers: { Authorization: header }, cache: "no-store" });
  if (!resp.ok) throw new Error("Credenciales incorrectas");
  state.authHeader = header;
  localStorage.setItem(STORAGE_KEYS.auth, header);
  saveCredentials(user, pass, remember);
  hideLogin();
  await init();
}

async function handleLogin() {
  const user = document.getElementById("login-user").value.trim();
  const pass = document.getElementById("login-pass").value;
  const remember = document.getElementById("login-remember").checked;
  if (!user || !pass) {
    showLogin("Introduce usuario y contraseña.", "error");
    return;
  }
  showLogin("Verificando credenciales...", "info");
  try {
    await loginWithCredentials(user, pass, remember);
  } catch (e) {
    localStorage.removeItem(STORAGE_KEYS.auth);
    showLogin(e.message || "Credenciales incorrectas", "error");
  }
}

document.getElementById("login-btn").addEventListener("click", handleLogin);
document.getElementById("login-user").addEventListener("keydown", (e) => { if (e.key === "Enter") handleLogin(); });
document.getElementById("login-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") handleLogin(); });

// ===================== Inicialización =====================
async function init() {
  await loadLibraries();
  await ensureDefaultLibrary();
  await loadComics(true);
  updateLibrarySummary();
  syncControls();
}

function syncControls() {
  document.getElementById("sort-select").value = state.filters.sort;
  document.getElementById("sort-order-btn").textContent = state.filters.order === "asc" ? "↑" : "↓";
  document.getElementById("page-size-select").value = String(state.limit);
  document.getElementById("view-mode-select").value = state.viewMode;
}

async function loadLibraries() {
  state.libraries = await api("/api/libraries");
  const sel = document.getElementById("library-select");
  sel.innerHTML = `<option value="">Todas las bibliotecas</option>` +
    state.libraries.map(l => `<option value="${l.id}">${l.name} (${l.comic_count})</option>`).join("");
  if (!state.currentLibraryId && state.libraries.length) {
    state.currentLibraryId = state.libraries[0].id;
  }
  if (state.currentLibraryId) sel.value = state.currentLibraryId;
  updateLibrarySummary();
}

async function ensureDefaultLibrary() {
  const defaults = [
    { name: "Repositorio Comics", root_path: "/comics" },
    { name: "Incoming aMule", root_path: "/incoming" },
  ];
  let added = false;
  for (const library of defaults) {
    if (state.libraries.some((existing) => existing.root_path === library.root_path)) continue;
    try {
      await api("/api/libraries", {
        method: "POST",
        body: JSON.stringify(library),
      });
      added = true;
    } catch (e) {
      // Si una ruta no existe o no está montada, el resto sigue siendo usable.
    }
  }
  if (added) {
    await loadLibraries();
  }
}

function updateLibrarySummary() {
  const panel = document.getElementById("library-summary");
  if (!panel) return;
  if (!state.libraries.length) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  const selected = state.libraries.find((l) => String(l.id) === String(state.currentLibraryId)) || state.libraries[0];
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div>
      <div class="summary-kicker">Biblioteca activa</div>
      <div class="summary-title">${escapeHtml(selected.name)}</div>
      <div class="summary-copy">${escapeHtml(selected.root_path)} · ${selected.comic_count} cómics indexados</div>
    </div>
    <div class="summary-chip">${state.comics.length} visibles</div>
  `;
}

sel_listeners: {
  document.getElementById("library-select").addEventListener("change", (e) => {
    state.currentLibraryId = e.target.value || null;
    loadComics(true);
  });
  document.getElementById("search-input").addEventListener("input", debounce((e) => {
    state.filters.q = e.target.value;
    loadComics(true);
  }, 400));
  document.getElementById("sort-select").addEventListener("change", (e) => {
    state.filters.sort = e.target.value;
    savePreferences();
    loadComics(true);
  });
  document.getElementById("sort-order-btn").addEventListener("click", () => {
    state.filters.order = state.filters.order === "asc" ? "desc" : "asc";
    syncControls(); savePreferences(); loadComics(true);
  });
  document.getElementById("page-size-select").addEventListener("change", (e) => {
    state.limit = Number(e.target.value); savePreferences(); loadComics(true);
  });
  document.getElementById("view-mode-select").addEventListener("change", (e) => {
    state.viewMode = e.target.value; savePreferences(); renderGrid();
  });
  document.querySelectorAll("[data-view]").forEach(btn => btn.addEventListener("click", () => {
    state.filters.view = btn.dataset.view;
    document.querySelectorAll("[data-view]").forEach(item => item.classList.toggle("active", item === btn));
    loadComics(true);
  }));
  document.getElementById("select-visible-btn").addEventListener("click", selectVisible);
  document.getElementById("load-more-btn").addEventListener("click", () => loadComics(false));
  document.getElementById("scan-btn").addEventListener("click", scanCurrentLibrary);
  document.getElementById("manage-libs-btn").addEventListener("click", openLibraryManager);
  document.getElementById("clear-selection-btn").addEventListener("click", clearSelection);
  document.getElementById("bulk-edit-btn").addEventListener("click", openBulkEditModal);
  document.getElementById("bulk-scrape-btn").addEventListener("click", openBulkScraperModal);
  document.getElementById("rename-btn").addEventListener("click", openRenameModal);
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ===================== Listado de cómics =====================
async function loadComics(reset) {
  if (reset) { state.offset = 0; state.comics = []; clearSelection(); }
  const params = new URLSearchParams({
    limit: state.limit, offset: state.offset,
    sort: state.filters.sort, order: state.filters.order,
  });
  if (state.currentLibraryId) params.set("library_id", state.currentLibraryId);
  if (state.filters.q) params.set("q", state.filters.q);
  const smartView = SMART_VIEWS[state.filters.view] || {};
  if (smartView.unread_only) params.set("unread_only", "true");
  if (smartView.missing) params.set("missing", smartView.missing);

  const results = await api(`/api/comics?${params.toString()}`);
  state.comics = reset ? results : [...state.comics, ...results];
  state.offset += results.length;
  document.getElementById("load-more-wrap").style.display = results.length < state.limit ? "none" : "block";
  document.getElementById("empty-state").classList.toggle("hidden", state.comics.length > 0);
  renderGrid();
  updateLibrarySummary();
}

function renderGrid() {
  const grid = document.getElementById("grid");
  grid.className = `comic-collection view-${state.viewMode}`;
  grid.innerHTML = state.comics.map(c => `
    <div class="comic-card relative" data-id="${c.id}">
      <input type="checkbox" class="checkbox-select" data-select-id="${c.id}" ${state.selection.has(c.id) ? "checked" : ""}>
      <img class="comic-cover w-full rounded shadow" loading="lazy"
           src="${c.cover_thumbnail ? `/api/reader/${c.id}/cover` : "/static/placeholder.svg"}"
           onerror="this.src='/static/placeholder.svg'">
      <div class="comic-info mt-1 text-xs">
        <div class="comic-series font-medium truncate">${escapeHtml(c.series || c.filename)}</div>
        <div class="comic-number text-neutral-400 truncate">#${escapeHtml(c.number || "?")} ${c.year ? "· " + c.year : ""}</div>
        <div class="comic-title truncate">${escapeHtml(c.title || "")}</div>
        <div class="comic-publisher text-neutral-500 truncate">${escapeHtml(c.publisher || "")}</div>
        <div class="comic-extra">${c.page_count || 0} págs. · ${escapeHtml(c.writer || "Sin guionista")} · ${escapeHtml(c.genre || "Sin género")}</div>
      </div>
      ${c.read ? '<span class="absolute top-1 right-1 bg-green-600 text-[10px] px-1 rounded">Leído</span>' : ""}
      ${c.format !== "cbz" ? `<span class="absolute bottom-14 right-1 bg-neutral-800 text-[10px] px-1 rounded uppercase">${c.format}</span>` : ""}
    </div>
  `).join("");

  grid.querySelectorAll("[data-select-id]").forEach(cb => {
    cb.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = parseInt(cb.dataset.selectId);
      if (cb.checked) state.selection.add(id); else state.selection.delete(id);
      updateSelectionBar();
    });
  });
  grid.querySelectorAll(".comic-card").forEach(card => {
    card.addEventListener("click", () => openComicDetail(parseInt(card.dataset.id)));
  });
}

function selectVisible() {
  state.comics.forEach(comic => state.selection.add(comic.id));
  document.querySelectorAll("[data-select-id]").forEach(cb => { cb.checked = true; });
  updateSelectionBar();
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

function clearSelection() {
  state.selection.clear();
  updateSelectionBar();
  document.querySelectorAll("[data-select-id]").forEach(cb => cb.checked = false);
}

function updateSelectionBar() {
  const bar = document.getElementById("selection-bar");
  const count = state.selection.size;
  bar.classList.toggle("hidden", count === 0);
  document.getElementById("selection-count").textContent = `${count} seleccionados`;
}

// ===================== Escaneo de biblioteca =====================
async function scanCurrentLibrary() {
  if (!state.currentLibraryId) {
    alert("Selecciona primero una biblioteca concreta en el desplegable para escanearla.");
    return;
  }
  await api(`/api/scan/${state.currentLibraryId}`, { method: "POST" }).catch(e => alert(e.message));
  pollScanStatus(state.currentLibraryId);
}

function pollScanStatus(libraryId) {
  const box = document.getElementById("scan-progress");
  box.classList.remove("hidden");
  const timer = setInterval(async () => {
    const status = await api(`/api/scan/${libraryId}/status`);
    box.textContent = `Escaneando… encontrados: ${status.found || 0}, nuevos: ${status.added || 0}, actualizados: ${status.updated || 0}, sin cambios: ${status.unchanged || 0}`;
    if (!status.running) {
      clearInterval(timer);
      box.textContent = status.error ? `Error en el escaneo: ${status.error}` : `Escaneo completado. Nuevos: ${status.added || 0}, actualizados: ${status.updated || 0}.`;
      setTimeout(() => box.classList.add("hidden"), 6000);
      await loadLibraries();
      await loadComics(true);
    }
  }, 1500);
}

// ===================== Gestión de bibliotecas =====================
function openLibraryManager() {
  const html = `
    <div class="modal-overlay" id="lib-modal">
      <div class="modal-box">
        <h2 class="text-lg font-semibold mb-4">Bibliotecas</h2>
        <div id="lib-list" class="space-y-2 mb-4">
          ${state.libraries.map(l => `
            <div class="flex items-center justify-between bg-neutral-800 rounded px-3 py-2 text-sm">
              <div><span class="font-medium">${escapeHtml(l.name)}</span> <span class="text-neutral-400">— ${escapeHtml(l.root_path)}</span> <span class="text-neutral-500">(${l.comic_count} cómics)</span></div>
              <button data-del-lib="${l.id}" class="text-red-400 hover:text-red-300 text-xs">Quitar del índice</button>
            </div>
          `).join("") || '<p class="text-neutral-400 text-sm">Aún no hay ninguna biblioteca añadida.</p>'}
        </div>
        <h3 class="text-sm font-medium mb-2">Añadir nueva biblioteca</h3>
        <p class="text-xs text-neutral-500 mb-2">La ruta debe existir DENTRO del contenedor (monta tu carpeta de cómics como volumen Docker, p.ej. en /comics).</p>
        <input id="new-lib-name" placeholder="Nombre (p.ej. Cómics US)" class="field-input mb-2">
        <input id="new-lib-path" placeholder="Ruta dentro del contenedor (p.ej. /comics/us)" class="field-input mb-3">
        <div class="flex gap-2">
          <button id="new-lib-save" class="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-sm">Crear</button>
          <button id="lib-modal-close" class="px-3 py-1.5 rounded bg-neutral-800 hover:bg-neutral-700 text-sm ml-auto">Cerrar</button>
        </div>
      </div>
    </div>`;
  document.getElementById("modal-root").innerHTML = html;
  document.getElementById("lib-modal-close").addEventListener("click", closeModal);
  document.querySelectorAll("[data-del-lib]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("Esto solo quita la biblioteca del índice de esta app. Nunca borra ficheros físicos. ¿Continuar?")) return;
      await api(`/api/libraries/${btn.dataset.delLib}`, { method: "DELETE" });
      await loadLibraries();
      openLibraryManager();
    });
  });
  document.getElementById("new-lib-save").addEventListener("click", async () => {
    const name = document.getElementById("new-lib-name").value.trim();
    const root_path = document.getElementById("new-lib-path").value.trim();
    if (!name || !root_path) return;
    try {
      await api("/api/libraries", { method: "POST", body: JSON.stringify({ name, root_path }) });
      await loadLibraries();
      openLibraryManager();
    } catch (e) { alert(e.message); }
  });
}

function closeModal() {
  document.getElementById("modal-root").innerHTML = "";
}

// ===================== Detalle / edición de un cómic =====================
async function openComicDetail(id) {
  const comic = await api(`/api/comics/${id}`);
  renderComicModal(comic);
}

function renderComicModal(comic) {
  const fieldsHtml = EDITABLE_FIELDS.map(([key, label]) => `
    <div>
      <label class="field-label">${label}</label>
      <input class="field-input" data-field="${key}" value="${escapeHtml(comic[key] ?? "")}">
    </div>
  `).join("");

  const html = `
    <div class="modal-overlay" id="comic-modal">
      <div class="modal-box">
        <div class="flex gap-4 mb-4">
          <img src="/api/reader/${comic.id}/cover" onerror="this.src='/static/placeholder.svg'" class="w-28 rounded shadow comic-cover">
          <div>
            <h2 class="text-lg font-semibold">${escapeHtml(comic.series || comic.filename)} #${escapeHtml(comic.number || "")}</h2>
            <p class="text-xs text-neutral-500 break-all">${escapeHtml(comic.path)}</p>
            <p class="text-xs text-neutral-500">Formato: ${comic.format.toUpperCase()} · ${comic.page_count} páginas</p>
            <div class="flex gap-2 mt-2 flex-wrap">
              <button id="read-btn" class="px-2 py-1 text-xs rounded bg-neutral-800 hover:bg-neutral-700">📖 Leer</button>
              ${comic.format !== "cbz" ? `<button id="convert-btn" class="px-2 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600">Convertir a CBZ</button>` : ""}
              <button id="scrape-btn" class="px-2 py-1 text-xs rounded bg-purple-700 hover:bg-purple-600">🔍 Buscar metadatos</button>
              <label class="flex items-center gap-1 text-xs"><input type="checkbox" id="read-toggle" ${comic.read ? "checked" : ""}> Leído</label>
            </div>
          </div>
        </div>

        <label class="field-label">Resumen</label>
        <textarea class="field-input mb-3" rows="3" data-field="summary">${escapeHtml(comic.summary)}</textarea>

        <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">${fieldsHtml}</div>

        <label class="field-label">Notas</label>
        <textarea class="field-input mb-4" rows="2" data-field="notes">${escapeHtml(comic.notes)}</textarea>

        <label class="flex items-center gap-2 text-sm mb-4">
          <input type="checkbox" id="write-comicinfo-cb" ${comic.format === "cbz" ? "" : "disabled"}>
          Escribir también en ComicInfo.xml dentro del archivo ${comic.format !== "cbz" ? "(conviértelo a cbz primero)" : ""}
        </label>

        <div class="flex gap-2">
          <button id="save-comic-btn" class="px-4 py-2 rounded bg-amber-600 hover:bg-amber-500 text-sm">Guardar</button>
          <button id="comic-modal-close" class="px-4 py-2 rounded bg-neutral-800 hover:bg-neutral-700 text-sm ml-auto">Cerrar</button>
        </div>
        <div id="comic-modal-msg" class="text-xs mt-2"></div>
      </div>
    </div>`;
  document.getElementById("modal-root").innerHTML = html;

  document.getElementById("comic-modal-close").addEventListener("click", closeModal);
  document.getElementById("read-btn").addEventListener("click", () => openReader(comic.id));
  document.getElementById("scrape-btn").addEventListener("click", () => openScraperModal(comic));
  const convertBtn = document.getElementById("convert-btn");
  if (convertBtn) convertBtn.addEventListener("click", () => convertComic(comic.id));

  document.getElementById("save-comic-btn").addEventListener("click", async () => {
    const changes = { write_comicinfo: document.getElementById("write-comicinfo-cb").checked };
    document.querySelectorAll("#comic-modal [data-field]").forEach(el => {
      let v = el.value;
      if (["year", "month", "day"].includes(el.dataset.field)) v = v === "" ? null : parseInt(v);
      changes[el.dataset.field] = v;
    });
    changes.read = document.getElementById("read-toggle").checked;
    try {
      await api(`/api/comics/${comic.id}`, { method: "PUT", body: JSON.stringify(changes) });
      document.getElementById("comic-modal-msg").textContent = "Guardado correctamente.";
      document.getElementById("comic-modal-msg").className = "text-xs mt-2 text-green-400";
      await loadComics(true);
    } catch (e) {
      document.getElementById("comic-modal-msg").textContent = "Error: " + e.message;
      document.getElementById("comic-modal-msg").className = "text-xs mt-2 text-red-400";
    }
  });
}

async function convertComic(id) {
  if (!confirm("Se creará una copia de seguridad del .cbr y se generará un .cbz junto a él. ¿Continuar?")) return;
  try {
    const res = await api("/api/convert", { method: "POST", body: JSON.stringify({ comic_id: id }) });
    alert(res.note);
    await loadComics(true);
    openComicDetail(id);
  } catch (e) { alert(e.message); }
}

// ===================== Lector básico =====================
async function openReader(id) {
  const info = await api(`/api/reader/${id}/pages`);
  let page = 0;
  const total = info.page_count;

  function render() {
    document.getElementById("modal-root").innerHTML = `
      <div class="modal-overlay" id="reader-modal">
        <div class="flex flex-col items-center gap-3 w-full h-full justify-center">
          <img src="/api/reader/${id}/page/${page}" class="max-h-[85vh] max-w-full object-contain rounded shadow-xl">
          <div class="flex items-center gap-4 bg-neutral-900/90 rounded-full px-4 py-2">
            <button id="prev-page" class="px-3 py-1 rounded bg-neutral-800 hover:bg-neutral-700">◀</button>
            <span class="text-sm">${page + 1} / ${total}</span>
            <button id="next-page" class="px-3 py-1 rounded bg-neutral-800 hover:bg-neutral-700">▶</button>
            <button id="reader-close" class="px-3 py-1 rounded bg-neutral-800 hover:bg-neutral-700">Cerrar</button>
          </div>
        </div>
      </div>`;
    document.getElementById("reader-close").addEventListener("click", async () => {
      await api(`/api/comics/${id}`, { method: "PUT", body: JSON.stringify({ last_page_read: page }) });
      closeModal();
    });
    document.getElementById("prev-page").addEventListener("click", () => { if (page > 0) { page--; render(); } });
    document.getElementById("next-page").addEventListener("click", () => { if (page < total - 1) { page++; render(); } });
  }
  render();
}

// ===================== Scrapers =====================
async function openScraperModal(comic) {
  const html = `
    <div class="modal-overlay" id="scraper-modal">
      <div class="modal-box">
        <h2 class="text-lg font-semibold mb-3">Buscar metadatos</h2>
        <div class="flex gap-2 mb-3">
          <select id="scraper-source" class="field-input" style="width:auto">
            <option value="whakoom">Whakoom</option>
            <option value="comicvine">ComicVine</option>
          </select>
          <input id="scraper-query" class="field-input" value="${escapeHtml(comic.series || comic.filename)}">
          <button id="scraper-search-btn" class="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-sm whitespace-nowrap">Buscar</button>
        </div>
        <div id="scraper-results" class="space-y-2 max-h-96 overflow-y-auto"></div>
        <button id="scraper-modal-close" class="mt-4 px-4 py-2 rounded bg-neutral-800 hover:bg-neutral-700 text-sm">Cerrar</button>
      </div>
    </div>`;
  document.getElementById("modal-root").innerHTML = html;
  document.getElementById("scraper-modal-close").addEventListener("click", () => openComicDetail(comic.id));

  async function doSearch() {
    const scraper = document.getElementById("scraper-source").value;
    const query = document.getElementById("scraper-query").value;
    const box = document.getElementById("scraper-results");
    box.innerHTML = '<p class="text-sm text-neutral-400">Buscando…</p>';
    try {
      const { results } = await api("/api/scrapers/search", { method: "POST", body: JSON.stringify({ scraper, query }) });
      if (!results.length) { box.innerHTML = '<p class="text-sm text-neutral-400">Sin resultados.</p>'; return; }
      box.innerHTML = results.map(r => `
        <div class="flex items-center justify-between bg-neutral-800 rounded px-3 py-2 text-sm">
          <div>
            <div class="font-medium">${escapeHtml(r.title || r.series)}</div>
            <div class="text-neutral-400 text-xs">${escapeHtml(r.publisher || "")} ${r.year ? "· " + r.year : ""}</div>
          </div>
          <button data-ref="${escapeHtml(r.ref)}" data-scraper="${scraper}" class="scraper-pick px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 text-xs">Explorar números</button>
        </div>
      `).join("");
      box.querySelectorAll(".scraper-pick").forEach(btn => {
        btn.addEventListener("click", () => showIssuesForSeries(comic, btn.dataset.scraper, btn.dataset.ref));
      });
    } catch (e) {
      box.innerHTML = `<p class="text-sm text-red-400">${escapeHtml(e.message)}</p>`;
    }
  }
  document.getElementById("scraper-search-btn").addEventListener("click", doSearch);
}

async function showIssuesForSeries(comic, scraper, ref) {
  const box = document.getElementById("scraper-results");
  box.innerHTML = '<p class="text-sm text-neutral-400">Cargando números…</p>';
  try {
    let issues;
    if (scraper === "whakoom") {
      issues = (await api(`/api/scrapers/whakoom/series-issues?series_url=${encodeURIComponent(ref)}`)).issues;
    } else {
      issues = (await api(`/api/scrapers/comicvine/volume-issues?volume_ref=${encodeURIComponent(ref)}`)).issues;
    }
    if (!issues.length) { box.innerHTML = '<p class="text-sm text-neutral-400">Sin números disponibles.</p>'; return; }
    box.innerHTML = issues.map(it => `
      <div class="flex items-center justify-between bg-neutral-800 rounded px-3 py-2 text-sm">
        <div>#${escapeHtml(it.number)} — ${escapeHtml(it.title || "")}</div>
        <button data-issue-ref="${escapeHtml(it.url || it.ref)}" class="apply-issue px-2 py-1 rounded bg-green-700 hover:bg-green-600 text-xs">Aplicar</button>
      </div>
    `).join("");
    box.querySelectorAll(".apply-issue").forEach(btn => {
      btn.addEventListener("click", () => applyScraperIssue(comic.id, scraper, btn.dataset.issueRef));
    });
  } catch (e) {
    box.innerHTML = `<p class="text-sm text-red-400">${escapeHtml(e.message)}</p>`;
  }
}

async function applyScraperIssue(comicId, scraper, ref) {
  const writeComicInfo = confirm("¿Escribir también estos metadatos en el ComicInfo.xml del archivo (solo cbz)? Aceptar = sí, Cancelar = solo en la base de datos.");
  try {
    await api("/api/scrapers/apply", {
      method: "POST",
      body: JSON.stringify({ comic_id: comicId, scraper, ref, write_comicinfo: writeComicInfo }),
    });
    await loadComics(true);
    openComicDetail(comicId);
  } catch (e) {
    alert("Error aplicando metadatos: " + e.message);
  }
}

async function openBulkScraperModal() {
  const selected = state.comics.filter(comic => state.selection.has(comic.id));
  const series = [...new Set(selected.map(comic => comic.series).filter(Boolean))];
  const suggested = series.length === 1 ? series[0] : "";
  const html = `
    <div class="modal-overlay" id="bulk-scraper-modal">
      <div class="modal-box modal-wide">
        <div class="modal-heading">
          <div><div class="eyebrow">Edición contra scraper</div><h2>Emparejar ${state.selection.size} cómics por número</h2></div>
          <button id="bulk-scraper-close" class="icon-button">×</button>
        </div>
        ${series.length > 1 ? `<div class="notice warning">Has seleccionado ${series.length} series diferentes. Es más seguro procesar una serie cada vez.</div>` : ""}
        <div class="scraper-search-row">
          <select id="bulk-scraper-source" class="control-select"><option value="whakoom">Whakoom</option><option value="comicvine">ComicVine</option></select>
          <input id="bulk-scraper-query" class="field-input" value="${escapeHtml(suggested)}" placeholder="Nombre de la serie">
          <button id="bulk-scraper-search" class="primary-button">Buscar serie</button>
        </div>
        <div id="bulk-scraper-results" class="scraper-workspace"><p class="muted">Elige una serie. Compararemos su numeración con los cómics seleccionados antes de modificar nada.</p></div>
      </div>
    </div>`;
  document.getElementById("modal-root").innerHTML = html;
  document.getElementById("bulk-scraper-close").addEventListener("click", closeModal);
  document.getElementById("bulk-scraper-search").addEventListener("click", async () => {
    const scraper = document.getElementById("bulk-scraper-source").value;
    const query = document.getElementById("bulk-scraper-query").value.trim();
    const box = document.getElementById("bulk-scraper-results");
    if (!query) return;
    box.innerHTML = '<p class="muted">Buscando series…</p>';
    try {
      const { results } = await api("/api/scrapers/search", { method: "POST", body: JSON.stringify({ scraper, query }) });
      box.innerHTML = results.length ? results.map(result => `
        <button class="series-result" data-series-ref="${escapeHtml(result.ref)}" data-source="${scraper}">
          <span><strong>${escapeHtml(result.title || result.series)}</strong><small>${escapeHtml(result.publisher || "")} ${result.year ? "· " + result.year : ""}</small></span><span>Comparar →</span>
        </button>`).join("") : '<p class="muted">No se encontraron series.</p>';
      box.querySelectorAll("[data-series-ref]").forEach(btn => btn.addEventListener("click", () => previewBulkScrape(btn.dataset.source, btn.dataset.seriesRef)));
    } catch (e) { box.innerHTML = `<p class="error-text">${escapeHtml(e.message)}</p>`; }
  });
}

async function previewBulkScrape(scraper, seriesRef) {
  const box = document.getElementById("bulk-scraper-results");
  box.innerHTML = '<p class="muted">Comparando números…</p>';
  try {
    const payload = { comic_ids: [...state.selection], scraper, series_ref: seriesRef, dry_run: true, write_comicinfo: false };
    const result = await api("/api/scrapers/bulk-apply", { method: "POST", body: JSON.stringify(payload) });
    box.innerHTML = `
      <div class="match-summary"><strong>${result.matched}</strong> coincidencias <span>·</span> <strong>${result.unmatched.length}</strong> sin emparejar</div>
      <div class="match-list">${result.preview.map(row => `<div><span>${escapeHtml(row.filename)}</span><span>#${escapeHtml(row.comic_number)} → #${escapeHtml(row.issue_number)} ${escapeHtml(row.issue_title || "")}</span></div>`).join("")}</div>
      ${result.unmatched.length ? `<details class="unmatched"><summary>Ver no emparejados</summary>${result.unmatched.map(row => `<div>${escapeHtml(row.filename)} (#${escapeHtml(row.number || "?")})</div>`).join("")}</details>` : ""}
      <label class="write-option"><input id="bulk-scrape-write" type="checkbox"> Escribir también ComicInfo.xml en los CBZ</label>
      <div class="modal-actions"><button id="bulk-scrape-apply" class="primary-button" ${result.matched ? "" : "disabled"}>Aplicar ${result.matched} coincidencias</button><button id="bulk-scrape-back" class="toolbar-button">Volver</button></div>
      <div id="bulk-scrape-status"></div>`;
    document.getElementById("bulk-scrape-back").addEventListener("click", openBulkScraperModal);
    document.getElementById("bulk-scrape-apply").addEventListener("click", async () => {
      const button = document.getElementById("bulk-scrape-apply");
      button.disabled = true; button.textContent = "Aplicando…";
      const finalResult = await api("/api/scrapers/bulk-apply", { method: "POST", body: JSON.stringify({ ...payload, dry_run: false, write_comicinfo: document.getElementById("bulk-scrape-write").checked }) });
      document.getElementById("bulk-scrape-status").innerHTML = `<div class="notice success">Actualizados ${finalResult.updated} cómics.${finalResult.errors.length ? ` ${finalResult.errors.length} requieren revisión.` : ""}</div>`;
      await loadComics(true);
    });
  } catch (e) { box.innerHTML = `<p class="error-text">${escapeHtml(e.message)}</p>`; }
}

// ===================== Edición en lote =====================
function openBulkEditModal() {
  const fieldsHtml = EDITABLE_FIELDS.concat([["summary", "Resumen"], ["notes", "Notas"]]).map(([key, label]) => `
    <div class="flex items-center gap-2">
      <input type="checkbox" data-bulk-enable="${key}">
      <label class="field-label flex-1 mb-0">${label}</label>
      <input class="field-input" style="width:60%" data-bulk-field="${key}" disabled>
    </div>
  `).join("");

  const html = `
    <div class="modal-overlay" id="bulk-modal">
      <div class="modal-box">
        <h2 class="text-lg font-semibold mb-2">Editar ${state.selection.size} cómics en lote</h2>
        <p class="text-xs text-neutral-500 mb-3">Marca la casilla de cada campo que quieras sobrescribir. Los campos no marcados no se tocan.</p>
        <div class="space-y-2 mb-4">${fieldsHtml}</div>
        <label class="flex items-center gap-2 text-sm mb-4">
          <input type="checkbox" id="bulk-write-comicinfo">
          Escribir también en ComicInfo.xml (solo aplica a los que ya sean .cbz)
        </label>
        <div class="flex gap-2">
          <button id="bulk-save-btn" class="px-4 py-2 rounded bg-amber-600 hover:bg-amber-500 text-sm">Aplicar a la selección</button>
          <button id="bulk-modal-close" class="px-4 py-2 rounded bg-neutral-800 hover:bg-neutral-700 text-sm ml-auto">Cancelar</button>
        </div>
        <div id="bulk-modal-msg" class="text-xs mt-2"></div>
      </div>
    </div>`;
  document.getElementById("modal-root").innerHTML = html;
  document.getElementById("bulk-modal-close").addEventListener("click", closeModal);
  document.querySelectorAll("[data-bulk-enable]").forEach(cb => {
    cb.addEventListener("change", () => {
      const input = document.querySelector(`[data-bulk-field="${cb.dataset.bulkEnable}"]`);
      input.disabled = !cb.checked;
    });
  });
  document.getElementById("bulk-save-btn").addEventListener("click", async () => {
    const changes = { write_comicinfo: document.getElementById("bulk-write-comicinfo").checked };
    document.querySelectorAll("[data-bulk-enable]:checked").forEach(cb => {
      const key = cb.dataset.bulkEnable;
      let v = document.querySelector(`[data-bulk-field="${key}"]`).value;
      if (["year", "month", "day"].includes(key)) v = v === "" ? null : parseInt(v);
      changes[key] = v;
    });
    try {
      const res = await api("/api/comics/bulk-edit", {
        method: "POST",
        body: JSON.stringify({ comic_ids: [...state.selection], changes }),
      });
      document.getElementById("bulk-modal-msg").textContent = `Actualizados: ${res.updated}. ${res.comicinfo_errors.length ? "Errores: " + res.comicinfo_errors.join("; ") : ""}`;
      document.getElementById("bulk-modal-msg").className = "text-xs mt-2 text-green-400";
      await loadComics(true);
    } catch (e) {
      document.getElementById("bulk-modal-msg").textContent = "Error: " + e.message;
      document.getElementById("bulk-modal-msg").className = "text-xs mt-2 text-red-400";
    }
  });
}

// ===================== Mover / renombrar en lote =====================
function openRenameModal() {
  const html = `
    <div class="modal-overlay" id="rename-modal">
      <div class="modal-box">
        <h2 class="text-lg font-semibold mb-2">Mover / renombrar ${state.selection.size} cómics</h2>
        <p class="text-xs text-neutral-500 mb-2">Tokens disponibles: {series} {number} {year} {publisher} {volume} {title}. La ruta es relativa a la raíz de la biblioteca de cada cómic.</p>
        <input id="rename-pattern" class="field-input mb-3" value="{publisher}/{series}/{series} #{number} ({year})">
        <div class="flex gap-2 mb-3">
          <button id="preview-btn" class="px-3 py-1.5 rounded bg-neutral-800 hover:bg-neutral-700 text-sm">Previsualizar</button>
        </div>
        <div id="rename-preview" class="space-y-1 max-h-72 overflow-y-auto text-xs text-neutral-400 mb-4"></div>
        <div class="flex gap-2">
          <button id="rename-apply-btn" class="px-4 py-2 rounded bg-amber-600 hover:bg-amber-500 text-sm" disabled>Aplicar movimiento</button>
          <button id="rename-modal-close" class="px-4 py-2 rounded bg-neutral-800 hover:bg-neutral-700 text-sm ml-auto">Cancelar</button>
        </div>
        <div id="rename-modal-msg" class="text-xs mt-2"></div>
      </div>
    </div>`;
  document.getElementById("modal-root").innerHTML = html;
  document.getElementById("rename-modal-close").addEventListener("click", closeModal);

  document.getElementById("preview-btn").addEventListener("click", async () => {
    const pattern = document.getElementById("rename-pattern").value;
    const { preview } = await api("/api/comics/rename-preview", {
      method: "POST",
      body: JSON.stringify({ comic_ids: [...state.selection], pattern, dry_run: true }),
    });
    document.getElementById("rename-preview").innerHTML = preview.map(p => `
      <div>${escapeHtml(p.current)} → <span class="text-amber-400">${escapeHtml(p.new_relative)}</span></div>
    `).join("");
    document.getElementById("rename-apply-btn").disabled = false;
  });

  document.getElementById("rename-apply-btn").addEventListener("click", async () => {
    if (!confirm("Esto moverá físicamente los ficheros en disco. ¿Continuar?")) return;
    const pattern = document.getElementById("rename-pattern").value;
    try {
      const res = await api("/api/comics/rename-apply", {
        method: "POST",
        body: JSON.stringify({ comic_ids: [...state.selection], pattern, dry_run: false }),
      });
      const errors = res.results.filter(r => !r.ok);
      document.getElementById("rename-modal-msg").textContent =
        `Movidos: ${res.results.length - errors.length}. ${errors.length ? "Errores: " + errors.map(e => e.error).join("; ") : ""}`;
      document.getElementById("rename-modal-msg").className = "text-xs mt-2 text-green-400";
      await loadComics(true);
    } catch (e) {
      document.getElementById("rename-modal-msg").textContent = "Error: " + e.message;
      document.getElementById("rename-modal-msg").className = "text-xs mt-2 text-red-400";
    }
  });
}

// ===================== Arranque =====================
if (state.authHeader) {
  fetch("/api/libraries", { headers: { Authorization: state.authHeader }, cache: "no-store" }).then(async (r) => {
    if (r.ok) {
      hideLogin();
      await init();
      return;
    }
    state.authHeader = null;
    localStorage.removeItem(STORAGE_KEYS.auth);
    fillSavedCredentials();
    showLogin("La sesión guardada ya no es válida.", "error");
  }).catch(() => {
    state.authHeader = null;
    localStorage.removeItem(STORAGE_KEYS.auth);
    fillSavedCredentials();
    showLogin("No se pudo validar la sesión guardada.", "error");
  });
} else {
  fillSavedCredentials();
  showLogin();
}

document.getElementById("logout-btn").addEventListener("click", () => {
  state.authHeader = null;
  localStorage.removeItem(STORAGE_KEYS.auth);
  showLogin("Sesión cerrada.", "info");
});
