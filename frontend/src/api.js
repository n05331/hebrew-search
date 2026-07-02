// שכבת גישה ל-API של ה-backend המקומי.
const BASE = "/api";

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => req("/health"),
  stats: () => req("/stats"),
  getRoots: () => req("/roots"),
  addRoot: (path) => req("/roots", { method: "POST", body: JSON.stringify({ path }) }),
  removeRoot: (path) => req("/roots", { method: "DELETE", body: JSON.stringify({ path }) }),
  startIndex: (paths) => req("/index", { method: "POST", body: JSON.stringify({ paths }) }),
  reindex: () => req("/reindex", { method: "POST" }),
  cancelIndex: () => req("/index/cancel", { method: "POST" }),
  progress: () => req("/progress"),
  watchStart: () => req("/watch/start", { method: "POST" }),
  watchStop: () => req("/watch/stop", { method: "POST" }),
  search: (params) => {
    const q = new URLSearchParams(params).toString();
    return req("/search?" + q);
  },
  searchPost: (body) => req("/search", { method: "POST", body: JSON.stringify(body) }),
  document: (id, q, opts = {}) =>
    req(
      "/document/" +
        id +
        "?" +
        new URLSearchParams({
          ...(q ? { q } : {}),
          ...(opts.exact ? { exact: "true" } : {}),
          ...(opts.whole_word ? { whole_word: "true" } : {}),
          ...(opts.fold_vy ? { fold_vy: "true" } : {}),
          ...(opts.fold_aa ? { fold_aa: "true" } : {}),
        })
    ),
  open: (path, page) => req("/open", { method: "POST", body: JSON.stringify({ path, page }) }),
  reveal: (path) => req("/reveal", { method: "POST", body: JSON.stringify({ path }) }),
  logs: (after, level) => req(`/logs?after=${after}&level=${level || "ALL"}`),
  errors: () => req("/errors"),
  exportDocumentUrl: (id) => BASE + "/export/document/" + id,
  exportResults: async (query, fileIds, includeFullText) => {
    const res = await fetch(BASE + "/export/results", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, file_ids: fileIds, include_full_text: includeFullText }),
    });
    if (!res.ok) throw new Error("ייצוא נכשל");
    const blob = await res.blob();
    triggerDownload(blob, "search_results.txt");
  },

  searchProgress: () => req("/search/progress"),

  // ---- ספרייה ----
  tree: () => req("/tree"),
  bookText: (path, chunk) =>
    req("/book/text?" + new URLSearchParams({ path, chunk: String(chunk || 0) })),
  bookToc: (path) => req("/book/toc?" + new URLSearchParams({ path })),
  bookSearch: (body) => req("/book/search", { method: "POST", body: JSON.stringify(body) }),
  syncPosition: (body) =>
    req("/book/sync-position", { method: "POST", body: JSON.stringify(body) }),
  mefarshim: (folder) => req("/mefarshim?" + new URLSearchParams({ folder })),
  fileUrl: (path) => BASE + "/file?" + new URLSearchParams({ path }),
  extractPdfSmart: (path) =>
    req("/extract/pdf-smart", { method: "POST", body: JSON.stringify({ path }) }),
  ocrRegion: (path, x, y, w, h) =>
    req("/ocr/region", { method: "POST", body: JSON.stringify({ path, x, y, w, h }) }),
  ocrEngines: () => req("/ocr/engines"),
  ocrRerun: () => req("/ocr/rerun", { method: "POST" }),

  // ---- הגדרות ----
  getSettings: () => req("/settings"),
  putSettings: (values) => req("/settings", { method: "PUT", body: JSON.stringify({ values }) }),
  fonts: () => req("/fonts"),

  // ---- לוח והעתקה / שמירת קבצים ----
  clipboard: (text) => req("/clipboard", { method: "POST", body: JSON.stringify({ text }) }),
  saveTextFile: (path, text, format) =>
    req("/export/text-file", { method: "POST", body: JSON.stringify({ path, text, format }) }),

  // ---- סימניות ----
  bookmarks: () => req("/bookmarks"),
  addBookmark: (b) => req("/bookmarks", { method: "POST", body: JSON.stringify(b) }),
  deleteBookmark: (id) => req("/bookmarks/" + id, { method: "DELETE" }),
  deleteBookmarks: (ids) => req("/bookmarks/delete", { method: "POST", body: JSON.stringify({ ids }) }),
};

export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadText(text, filename) {
  triggerDownload(new Blob([text], { type: "text/plain;charset=utf-8" }), filename);
}

// הסרת ניקוד/טעמים בצד הלקוח
export function stripNiqqud(text) {
  return text.replace(/[\u05B0-\u05C7]/g, "");
}
export function stripTeamim(text) {
  return text.replace(/[\u0591-\u05AF]/g, "");
}

// בורר תיקיות דרך גשר pywebview (אם קיים)
export async function pickFolder() {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder) {
    const result = await window.pywebview.api.pick_folder();
    return result || null;
  }
  return null;
}

// דיאלוג "שמירה בשם" נייטיב דרך pywebview. מחזיר נתיב או null.
export async function pickSaveFile(defaultName, fileType) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.save_file_dialog) {
    const result = await window.pywebview.api.save_file_dialog(defaultName, fileType);
    return result || null;
  }
  return null;
}

// העתקה ללוח: דרך השרת (נקלט ב-Windows+V), עם נפילה ל-navigator.clipboard.
export async function copyText(text) {
  try {
    await api.clipboard(text);
    return true;
  } catch (e) {}
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    return false;
  }
}
