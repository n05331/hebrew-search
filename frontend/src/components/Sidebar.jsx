import React, { useState } from "react";
import { api, pickFolder } from "../api.js";

export default function Sidebar({ stats, roots, progress, filters, setFilters, onChanged, onToast }) {
  const [manualPath, setManualPath] = useState("");
  const running = progress && progress.running;

  async function addFolder() {
    let path = await pickFolder();
    if (!path) path = manualPath.trim();
    if (!path) {
      onToast("בחרו תיקייה או הדביקו נתיב", "error");
      return;
    }
    try {
      await api.addRoot(path);
      setManualPath("");
      onChanged();
      onToast("התיקייה נוספה: " + path, "ok");
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function removeFolder(path) {
    await api.removeRoot(path);
    onChanged();
  }

  async function startIndex() {
    try {
      await api.startIndex(roots);
      onToast("האינדוקס החל", "ok");
      onChanged();
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function reindex() {
    try {
      await api.reindex();
      onToast("אינדוקס מחדש החל", "ok");
      onChanged();
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function cancel() {
    await api.cancelIndex();
    onToast("בקשת ביטול נשלחה", "ok");
  }

  const pct = progress && progress.total ? Math.round((progress.processed / progress.total) * 100) : 0;

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-icon">🔎</span>
        <span className="brand-name">חיפוש עברי</span>
      </div>

      <section className="panel">
        <h3>תיקיות לאינדוקס</h3>
        <div className="folder-list">
          {roots.length === 0 && <div className="muted">לא נוספו תיקיות עדיין</div>}
          {roots.map((r) => (
            <div className="folder-row" key={r} title={r}>
              <span className="folder-path">{r}</span>
              <button className="icon-btn" onClick={() => removeFolder(r)} title="הסר">✕</button>
            </div>
          ))}
        </div>
        <div className="add-folder">
          <input
            type="text"
            placeholder="הדביקו נתיב תיקייה…"
            value={manualPath}
            onChange={(e) => setManualPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addFolder()}
          />
          <button className="btn" onClick={addFolder}>הוסף</button>
        </div>
        <div className="index-actions">
          <button className="btn btn-primary" onClick={startIndex} disabled={running || roots.length === 0}>
            בנה אינדקס
          </button>
          <button className="btn" onClick={reindex} disabled={running || roots.length === 0}>
            אינדוקס מחדש
          </button>
          {running && (
            <button className="btn btn-danger" onClick={cancel}>
              עצור
            </button>
          )}
        </div>

        {running && (
          <div className="progress">
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: pct + "%" }} />
            </div>
            <div className="progress-text">
              {progress.phase === "scanning" ? "סורק…" : `מאנדקס ${progress.processed}/${progress.total}`}
            </div>
            <div className="progress-current" title={progress.current}>{progress.current}</div>
          </div>
        )}

        {progress.ocr && (progress.ocr.running || progress.ocr.pending > 0) && (
          <div className="progress ocr-progress">
            <div className="progress-text">
              OCR ברקע · {progress.ocr.pending} בתור
              {progress.ocr.pages > 0 ? ` · עמוד ${progress.ocr.page}/${progress.ocr.pages}` : ""}
            </div>
            {progress.ocr.pages > 0 && (
              <div className="progress-bar">
                <div
                  className="progress-fill ocr-fill"
                  style={{ width: Math.round((progress.ocr.page / progress.ocr.pages) * 100) + "%" }}
                />
              </div>
            )}
            {progress.ocr.current && (
              <div className="progress-current" title={progress.ocr.current}>{progress.ocr.current}</div>
            )}
          </div>
        )}
      </section>

      <section className="panel">
        <h3>סינון תוצאות</h3>
        <label className="filter-label">סוג קובץ</label>
        <div className="ext-filters">
          {[".pdf", ".docx", ".txt", ".png", ".jpg"].map((ext) => (
            <label key={ext} className="chk">
              <input
                type="checkbox"
                checked={filters.exts.includes(ext)}
                onChange={(e) => {
                  const next = e.target.checked
                    ? [...filters.exts, ext]
                    : filters.exts.filter((x) => x !== ext);
                  setFilters({ ...filters, exts: next });
                }}
              />
              {ext}
            </label>
          ))}
        </div>
        <label className="filter-label">תיקייה מכילה</label>
        <input
          type="text"
          placeholder="למשל C:\\Docs"
          value={filters.folder}
          onChange={(e) => setFilters({ ...filters, folder: e.target.value })}
        />
      </section>

      <section className="panel stats-panel">
        <h3>סטטוס</h3>
        <div className="stat-row"><span>קבצים באינדקס</span><b>{stats.indexed_files ?? 0}</b></div>
        <div className="stat-row"><span>סה״כ קבצים</span><b>{stats.total_files ?? 0}</b></div>
        <div className="stat-row"><span>שגיאות</span><b>{stats.error_files ?? 0}</b></div>
        <div className="stat-row">
          <span>OCR</span>
          <b className={stats.ocr_available ? "ok" : "off"}>{stats.ocr_available ? "זמין" : "כבוי"}</b>
        </div>
        <div className="stat-row">
          <span>מעקב חי</span>
          <label className="switch">
            <input
              type="checkbox"
              checked={!!stats.watch_active}
              onChange={async (e) => {
                try {
                  e.target.checked ? await api.watchStart() : await api.watchStop();
                  onChanged();
                } catch (err) {
                  onToast(err.message, "error");
                }
              }}
            />
            <span className="slider" />
          </label>
        </div>
      </section>
    </aside>
  );
}
