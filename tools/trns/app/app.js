// trns PWA — translator logic
// Mirrors core/translator.py: hits the free googleapis endpoint,
// unwraps the 3-level nested array, retries on transient failures.

const MAX_CHARS = 4500;
const ENDPOINT = "https://translate.googleapis.com/translate_a/single";

// Pragmatic subset of the 100+ languages the endpoint supports.
// Mirrors core/utils.py:LANGUAGES, normalised to a { code, name } array.
const LANGS = [
  ["auto", "Auto-detect"],
  ["en", "English"],
  ["pl", "Polish"],
  ["de", "German"],
  ["fr", "French"],
  ["es", "Spanish"],
  ["it", "Italian"],
  ["pt", "Portuguese"],
  ["nl", "Dutch"],
  ["ru", "Russian"],
  ["uk", "Ukrainian"],
  ["cs", "Czech"],
  ["sk", "Slovak"],
  ["ro", "Romanian"],
  ["hu", "Hungarian"],
  ["bg", "Bulgarian"],
  ["el", "Greek"],
  ["tr", "Turkish"],
  ["sv", "Swedish"],
  ["no", "Norwegian"],
  ["da", "Danish"],
  ["fi", "Finnish"],
  ["is", "Icelandic"],
  ["et", "Estonian"],
  ["lv", "Latvian"],
  ["lt", "Lithuanian"],
  ["ga", "Irish"],
  ["cy", "Welsh"],
  ["eu", "Basque"],
  ["ca", "Catalan"],
  ["gl", "Galician"],
  ["mt", "Maltese"],
  ["sq", "Albanian"],
  ["sr", "Serbian"],
  ["hr", "Croatian"],
  ["bs", "Bosnian"],
  ["sl", "Slovenian"],
  ["mk", "Macedonian"],
  ["be", "Belarusian"],
  ["ka", "Georgian"],
  ["hy", "Armenian"],
  ["az", "Azerbaijani"],
  ["kk", "Kazakh"],
  ["ky", "Kyrgyz"],
  ["uz", "Uzbek"],
  ["tg", "Tajik"],
  ["tk", "Turkmen"],
  ["mn", "Mongolian"],
  ["ar", "Arabic"],
  ["he", "Hebrew"],
  ["fa", "Persian"],
  ["ur", "Urdu"],
  ["hi", "Hindi"],
  ["bn", "Bengali"],
  ["pa", "Punjabi"],
  ["gu", "Gujarati"],
  ["mr", "Marathi"],
  ["ta", "Tamil"],
  ["te", "Telugu"],
  ["kn", "Kannada"],
  ["ml", "Malayalam"],
  ["si", "Sinhala"],
  ["ne", "Nepali"],
  ["my", "Burmese"],
  ["km", "Khemer"],
  ["lo", "Lao"],
  ["th", "Thai"],
  ["vi", "Vietnamese"],
  ["id", "Indonesian"],
  ["ms", "Malay"],
  ["tl", "Tagalog"],
  ["jv", "Javanese"],
  ["su", "Sundanese"],
  ["ja", "Japanese"],
  ["ko", "Korean"],
  ["zh", "Chinese"],
  ["zh-cn", "Chinese (Simplified)"],
  ["zh-tw", "Chinese (Traditional)"],
  ["yi", "Yiddish"],
  ["eo", "Esperanto"],
  ["la", "Latin"],
  ["sw", "Swahili"],
  ["af", "Afrikaans"],
  ["am", "Amharic"],
  ["ha", "Hausa"],
  ["ig", "Igbo"],
  ["yo", "Yoruba"],
  ["zu", "Zulu"],
  ["xh", "Xhosa"],
  ["st", "Sesotho"],
  ["so", "Somali"],
  ["mg", "Malagasy"],
  ["mi", "Maori"],
  ["sm", "Samoan"],
  ["haw", "Hawaiian"],
].map(([code, name]) => ({ code, name }));

const NAME_BY_CODE = Object.fromEntries(LANGS.map((l) => [l.code, l.name]));

function langName(code) {
  return NAME_BY_CODE[code] || code.toUpperCase();
}
function langLabel(code) {
  return code === "auto" ? "AUTO" : code.toUpperCase();
}

// --- translation ---------------------------------------------------------

class TranslationError extends Error {}

async function translateOnce(text, source, target, signal) {
  if (!text.trim()) return { text: "", detected: null };
  if (source === target) return { text, detected: source };

  const params = new URLSearchParams({
    client: "gtx",
    sl: source,
    tl: target,
    dt: "t",
    ie: "UTF-8",
    oe: "UTF-8",
    q: text,
  });
  const url = `${ENDPOINT}?${params}`;

  let resp;
  try {
    resp = await fetch(url, {
      method: "GET",
      signal,
      headers: {
        // A real-browser UA is required; bare fetch UAs get blank 4xx.
        Accept: "application/json,text/plain,*/*",
      },
    });
  } catch (e) {
    const msg = (e && (e.message || String(e))) || "Network error";
    throw new TranslationError(
      /abort/i.test(msg)
        ? "Cancelled."
        : /fetch|network|failed/i.test(msg)
          ? `Could not reach translation endpoint: ${msg}`
          : `Network error: ${msg}`,
    );
  }
  if (!resp.ok) {
    throw new TranslationError(
      `Translation endpoint returned HTTP ${resp.status}. ` +
        `Check your internet connection or try a shorter phrase.`,
    );
  }
  let payload;
  try {
    payload = await resp.json();
  } catch (e) {
    throw new TranslationError(`Bad JSON from endpoint: ${e.message}`);
  }
  const [translated, detected] = unwrap(payload);
  return { text: translated, detected };
}

// mirrors core/translator.py:translate_with_retry
async function translate(text, source, target, { attempts = 3, signal } = {}) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await translateOnce(text, source, target, signal);
    } catch (e) {
      lastErr = e;
      if (e instanceof TranslationError && e.message === "Cancelled.") throw e;
      const msg = String(e.message || "").toLowerCase();
      const transient =
        msg.includes("timed out") ||
        msg.includes("could not reach") ||
        msg.includes("network error") ||
        /http 5\d\d/.test(msg);
      if (!transient || i === attempts - 1) break;
      await sleep(600 * (i + 1));
    }
  }
  throw lastErr;
}

function unwrap(payload) {
  try {
    const sentences = payload[0];
    const detected = payload[2] || null;
    if (!Array.isArray(sentences)) throw new Error("shape");
    const out = [];
    for (const chunk of sentences) {
      if (!Array.isArray(chunk) || chunk.length === 0) continue;
      out.push(chunk[0] || "");
    }
    return [out.join(""), detected];
  } catch {
    throw new TranslationError("Malformed response from translation endpoint");
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function isOnline() {
  if (!navigator.onLine) return false;
  try {
    const r = await fetch("https://translate.googleapis.com/generate_204", {
      method: "GET",
      cache: "no-store",
    });
    return r.ok || r.status === 204;
  } catch {
    return false;
  }
}

// --- persistent settings ------------------------------------------------

const SETTINGS_KEY = "trns.settings.v1";
const HISTORY_KEY = "trns.history.v1";

const DEFAULT_SETTINGS = { source: "en", target: "pl" };

function loadSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    return {
      source: typeof raw.source === "string" ? raw.source : DEFAULT_SETTINGS.source,
      target: typeof raw.target === "string" ? raw.target : DEFAULT_SETTINGS.target,
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function saveSettings(s) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {}
}

function loadHistory() {
  try {
    const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(raw) ? raw.slice(0, 12) : [];
  } catch {
    return [];
  }
}

function saveHistory(h) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, 12)));
  } catch {}
}

function pushHistory(entry) {
  const list = loadHistory();
  // dedupe by source text + target — same source in either direction
  const next = [entry, ...list.filter((h) => h.src !== entry.src || h.tgt !== entry.tgt)].slice(0, 12);
  saveHistory(next);
  return next;
}

function clearHistory() {
  saveHistory([]);
}

// --- DOM -----------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  srcBtn: $("#srcBtn"),
  tgtBtn: $("#tgtBtn"),
  srcCode: $("#srcCode"),
  srcName: $("#srcName"),
  tgtCode: $("#tgtCode"),
  tgtName: $("#tgtName"),
  swapBtn: $("#swapBtn"),
  srcText: $("#srcText"),
  srcLabel: $("#srcLabel"),
  tgtLabel: $("#tgtLabel"),
  srcClear: $("#srcClear"),
  translateBtn: $("#translateBtn"),
  tgtText: $("#tgtText"),
  copyBtn: $("#copyBtn"),
  copyLabel: $("#copyLabel"),
  detectLabel: $("#detectLabel"),
  charCount: $("#charCount"),
  history: $("#history"),
  historyList: $("#historyList"),
  clearHistory: $("#clearHistory"),
  toast: $("#toast"),
  sheet: $("#sheet"),
  sheetList: $("#sheetList"),
  sheetSearch: $("#sheetSearch"),
  sheetTitle: $("#sheetTitle"),
};

const state = { ...loadSettings() };

function renderLanguages() {
  els.srcCode.textContent = langLabel(state.source);
  els.srcName.textContent = langName(state.source);
  els.tgtCode.textContent = langLabel(state.target);
  els.tgtName.textContent = langName(state.target);
  els.srcLabel.textContent = langName(state.source);
  els.tgtLabel.textContent = langName(state.target);
}

function renderCharCount() {
  const n = (els.srcText.value || "").length;
  els.charCount.textContent = `${n} / ${MAX_CHARS}`;
}

function renderHistory() {
  const list = loadHistory();
  if (list.length === 0) {
    els.history.hidden = true;
    els.historyList.innerHTML = "";
    return;
  }
  els.history.hidden = false;
  els.historyList.innerHTML = list
    .map(
      (h, i) => `
      <li class="history-item" data-idx="${i}">
        <div class="h-src">${escapeHtml(h.src)}</div>
        <div class="h-tgt">${escapeHtml(h.tgt)}</div>
        <div class="h-meta">${langLabel(h.srcCode)} → ${langLabel(h.tgtCode)} · ${formatTime(h.ts)}</div>
      </li>`,
    )
    .join("");
  $$("#historyList .history-item").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = Number(el.getAttribute("data-idx"));
      const item = list[idx];
      if (!item) return;
      els.srcText.value = item.src;
      state.source = item.srcCode;
      state.target = item.tgtCode;
      renderLanguages();
      renderCharCount();
      doTranslate();
      saveSettings(state);
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function formatTime(ts) {
  try {
    const d = new Date(ts);
    const today = new Date();
    if (d.toDateString() === today.toDateString()) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString();
  } catch { return ""; }
}

let toastTimer = null;
function toast(msg, kind = "") {
  els.toast.textContent = msg;
  els.toast.classList.remove("err", "ok");
  if (kind) els.toast.classList.add(kind);
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (els.toast.hidden = true), 2200);
}

// --- translation pipeline ------------------------------------------------

let inflight = null;

async function doTranslate() {
  const text = els.srcText.value || "";
  if (!text.trim()) {
    setResult("", { detected: null, empty: true, hint: "Type something above to translate." });
    return;
  }
  if (text.length > MAX_CHARS) {
    setResult("", {
      empty: true,
      error: `Input is ${text.length} chars; the limit is ${MAX_CHARS}. Try a shorter phrase.`,
    });
    return;
  }
  if (state.source === state.target && state.source !== "auto") {
    setResult(text, { detected: state.source });
    return;
  }

  // cancel previous in-flight request
  if (inflight) inflight.abort();
  const ctrl = new AbortController();
  inflight = ctrl;
  els.translateBtn.classList.add("loading");
  els.translateBtn.disabled = true;

  try {
    const { text: out, detected } = await translate(text, state.source, state.target, {
      signal: ctrl.signal,
    });
    if (ctrl.signal.aborted) return;
    setResult(out, { detected });
    pushHistory({
      src: text,
      tgt: out,
      srcCode: state.source,
      tgtCode: state.target,
      ts: Date.now(),
    });
    renderHistory();
  } catch (e) {
    if (ctrl.signal.aborted) return;
    const msg = e && e.message ? e.message : "Translation failed";
    setResult("", { error: msg });
  } finally {
    if (inflight === ctrl) inflight = null;
    els.translateBtn.classList.remove("loading");
    els.translateBtn.disabled = false;
  }
}

function setResult(text, { detected = null, empty = false, hint = "", error = null } = {}) {
  if (error) {
    els.tgtText.dataset.empty = "false";
    els.tgtText.innerHTML = `<span class="err">${escapeHtml(error)}</span>`;
    els.detectLabel.textContent = "";
    return;
  }
  if (empty) {
    els.tgtText.dataset.empty = "true";
    els.tgtText.textContent = hint || "Your translation will appear here.";
    els.detectLabel.textContent = "";
    return;
  }
  els.tgtText.dataset.empty = "false";
  els.tgtText.textContent = text;
  if (detected && state.source === "auto" && detected !== "auto" && detected !== state.target) {
    els.detectLabel.textContent = `detected: ${langName(detected)}`;
  } else {
    els.detectLabel.textContent = "";
  }
}

// --- language picker sheet ----------------------------------------------

function openSheet(which) {
  const isSource = which === "source";
  els.sheetTitle.textContent = isSource ? "Source language" : "Target language";
  const exclude = isSource ? null : state.source;
  const items = LANGS.filter((l) => !exclude || l.code !== state.source || l.code === "auto" ? true : l.code !== exclude);
  // For target picker, hide "auto" (auto can't be a target)
  const filtered = isSource ? items : items.filter((l) => l.code !== "auto");
  const selected = isSource ? state.source : state.target;

  els.sheetList.innerHTML = filtered
    .map(
      (l) => `
      <li class="sheet-item" role="option" data-code="${l.code}" ${
        l.code === selected ? 'aria-selected="true"' : ""
      }>
        <span class="item-name">${escapeHtml(l.name)}</span>
        <span class="item-code">${langLabel(l.code)}</span>
      </li>`,
    )
    .join("");

  els.sheetSearch.value = "";
  els.sheet.hidden = false;
  setTimeout(() => els.sheetSearch.focus(), 60);

  function close() {
    els.sheet.hidden = true;
    els.sheetList.onclick = null;
    document.removeEventListener("keydown", onKey);
  }
  function onKey(e) {
    if (e.key === "Escape") close();
  }
  document.addEventListener("keydown", onKey);

  els.sheetList.onclick = (e) => {
    const li = e.target.closest(".sheet-item");
    if (!li) return;
    const code = li.getAttribute("data-code");
    if (isSource) {
      state.source = code;
      if (state.target === code && code !== "auto") {
        // auto-flip target to avoid same==same
        const fallback = code === "en" ? "pl" : "en";
        state.target = fallback;
      }
    } else {
      // avoid same==same (unless source is auto)
      if (state.source !== "auto" && code === state.source) {
        toast("Source and target can't match", "err");
        return;
      }
      state.target = code;
    }
    saveSettings(state);
    renderLanguages();
    close();
    if (els.srcText.value.trim()) doTranslate();
  };

  els.sheetSearch.oninput = (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$("#sheetList .sheet-item").forEach((li) => {
      const txt = li.textContent.toLowerCase();
      li.style.display = !q || txt.includes(q) ? "" : "none";
    });
  };
}

// --- swiping the swap button feels nice; supporting a tiny swipe on the lang-row as well.
let touchStart = null;
els.srcText.addEventListener("input", renderCharCount);
els.srcText.addEventListener("keydown", (e) => {
  // Enter without shift → translate; ⌘/Ctrl+Enter also ok
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    doTranslate();
  }
});

// quick offline check on load
window.addEventListener("online", () => toast("Back online", "ok"));
window.addEventListener("offline", () => toast("You're offline"));

// bootstrap
els.translateBtn.addEventListener("click", doTranslate);
els.swapBtn.addEventListener("click", () => {
  if (state.source === "auto") {
    toast("Auto-detect can't be swapped", "err");
    return;
  }
  [state.source, state.target] = [state.target, state.source];
  saveSettings(state);
  renderLanguages();
  if (els.srcText.value.trim()) doTranslate();
});

els.srcBtn.addEventListener("click", () => openSheet("source"));
els.tgtBtn.addEventListener("click", () => openSheet("target"));
els.sheet.querySelectorAll("[data-close]").forEach((el) =>
  el.addEventListener("click", () => (els.sheet.hidden = true)),
);

els.srcClear.addEventListener("click", () => {
  els.srcText.value = "";
  renderCharCount();
  setResult("", { empty: true, hint: "Your translation will appear here." });
  els.srcText.focus();
});

els.copyBtn.addEventListener("click", async () => {
  const out = els.tgtText.textContent || "";
  if (!out || els.tgtText.dataset.empty === "true") return;
  try {
    await navigator.clipboard.writeText(out);
    toast("Copied", "ok");
    els.copyLabel.textContent = "Copied";
    setTimeout(() => (els.copyLabel.textContent = "Copy"), 1200);
  } catch {
    toast("Couldn't copy", "err");
  }
});

els.clearHistory.addEventListener("click", () => {
  clearHistory();
  renderHistory();
});

renderLanguages();
renderCharCount();
renderHistory();

isOnline().then((ok) => {
  if (!ok) toast("Offline. Translation needs internet.", "err");
});

// service worker (offline shell + last-known cache)
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {
      /* silent: PWA still works without offline support */
    });
  });
}
