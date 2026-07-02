import React, { useEffect, useMemo, useState } from "react";
import { api, pickFolder } from "../api.js";

// חלונית "הגדרות": השינויים נשמרים רק בלחיצה על "שמור הגדרות".
export default function SettingsView({ settings, onSettingsChanged, roots, onRootsChanged, progress, onToast }) {
  const [fonts, setFonts] = useState([]);
  const [fontFilter, setFontFilter] = useState("");
  const [local, setLocal] = useState(settings);
  const [dirty, setDirty] = useState(false);
  const [manualPath, setManualPath] = useState("");
  const running = progress && progress.running;

  useEffect(() => {
    // סנכרון מהשרת רק כשאין שינויים מקומיים שלא נשמרו
    if (!dirty) setLocal(settings);
  }, [settings]);

  useEffect(() => {
    api.fonts().then((r) => setFonts(r.fonts)).catch(() => {});
  }, []);

  function edit(partial) {
    setLocal((prev) => ({ ...prev, ...partial }));
    setDirty(true);
  }

  async function saveAll() {
    try {
      await api.putSettings(local);
      onSettingsChanged(local);
      setDirty(false);
      onToast("ההגדרות נשמרו", "ok");
    } catch (e) {
      onToast("שמירת הגדרות נכשלה: " + e.message, "error");
    }
  }

  async function addFolder() {
    let path = await pickFolder();
    if (!path) path = manualPath.trim();
    if (!path) { onToast("בחרו תיקייה או הדביקו נתיב", "error"); return; }
    try {
      await api.addRoot(path);
      setManualPath("");
      onRootsChanged();
      onToast("התיקייה נוספה", "ok");
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function startIndex() {
    try { await api.startIndex(roots); onToast("האינדוקס החל", "ok"); } catch (e) { onToast(e.message, "error"); }
  }
  async function reindex() {
    try { await api.reindex(); onToast("אינדוקס מחדש החל", "ok"); } catch (e) { onToast(e.message, "error"); }
  }

  const unlimited = String(local.result_limit || "0") === "0";

  const filteredFonts = useMemo(() => {
    const t = fontFilter.trim().toLowerCase();
    if (!t) return fonts;
    return fonts.filter((f) => f.toLowerCase().includes(t));
  }, [fonts, fontFilter]);

  return (
    <div className="settings-view">
      <div className="settings-header">
        <h2>הגדרות</h2>
        <div className="settings-save">
          {dirty && <span className="muted">יש שינויים שלא נשמרו</span>}
          <button className="btn btn-primary" onClick={saveAll} disabled={!dirty}>
            שמור הגדרות
          </button>
        </div>
      </div>

      <section className="settings-section">
        <h3>תצוגת ספרים</h3>
        <div className="setting-row">
          <label>גודל גופן לטקסט מוצג</label>
          <input
            type="number" min="10" max="60"
            value={local.font_size || "30"}
            onChange={(e) => edit({ font_size: e.target.value })}
          />
        </div>
        <div className="setting-row">
          <label>גודל גופן לתוצאות חיפוש</label>
          <input
            type="number" min="10" max="60"
            value={local.result_font_size || "25"}
            onChange={(e) => edit({ result_font_size: e.target.value })}
          />
        </div>
        <div className="setting-row">
          <label>גופן לתצוגת ספרים</label>
          <div className="setting-font">
            <input
              type="text"
              placeholder="חיפוש גופן…"
              value={fontFilter}
              onChange={(e) => setFontFilter(e.target.value)}
            />
            <select
              size={Math.min(8, Math.max(3, filteredFonts.length + 1))}
              value={local.font_family || ""}
              onChange={(e) => edit({ font_family: e.target.value })}
            >
              <option value="FrankRuehl" style={{ fontFamily: "FrankRuehl" }}>
                FrankRuehl (ברירת מחדל)
              </option>
              {filteredFonts.map((f) => (
                <option key={f} value={f} style={{ fontFamily: f }}>{f}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="setting-row">
          <label>ספר עם טקסט + PDF — מה לפתוח קודם</label>
          <select
            value={local.at_default || "text"}
            onChange={(e) => edit({ at_default: e.target.value })}
          >
            <option value="text">טקסט</option>
            <option value="pdf">PDF</option>
          </select>
        </div>
      </section>

      <section className="settings-section">
        <h3>חיפוש</h3>
        <div className="setting-row">
          <label>מגבלת תוצאות</label>
          <div className="setting-inline">
            <label className="chk">
              <input
                type="checkbox"
                checked={unlimited}
                onChange={(e) => edit({ result_limit: e.target.checked ? "0" : "200" })}
              />
              ללא הגבלה
            </label>
            {!unlimited && (
              <input
                type="number" min="10" max="10000"
                value={local.result_limit}
                onChange={(e) => edit({ result_limit: e.target.value })}
              />
            )}
          </div>
        </div>
        <div className="setting-row">
          <label>מילים לפני ואחרי בקטע התוצאה</label>
          <input
            type="number" min="3" max="200"
            value={local.snippet_words || "50"}
            onChange={(e) => edit({ snippet_words: e.target.value })}
          />
        </div>
        <div className="setting-row">
          <label>מרחק מרבי בין מילים בחיפוש לא-מדויק (מילים)</label>
          <input
            type="number" min="0" max="1000"
            title="0 = ללא הגבלת מרחק"
            value={local.proximity_words || "30"}
            onChange={(e) => edit({ proximity_words: e.target.value })}
          />
        </div>
      </section>

      <section className="settings-section">
        <h3>תיקיות מקור הקבצים</h3>
        <div className="folder-list">
          {roots.length === 0 && <div className="muted">לא נוספו תיקיות עדיין</div>}
          {roots.map((r) => (
            <div className="folder-row" key={r} title={r}>
              <span className="folder-path">{r}</span>
              <button
                className="icon-btn"
                onClick={async () => { await api.removeRoot(r); onRootsChanged(); }}
                title="הסר"
              >✕</button>
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
          {running && <button className="btn btn-danger" onClick={() => api.cancelIndex()}>עצור</button>}
        </div>
        {progress && progress.phase === "done" && !running && progress.total > 0 && (
          <div className="index-summary">
            האינדוקס האחרון הסתיים: {progress.indexed} חדשים/עודכנו, {progress.skipped} דולגו (ללא שינוי),
            {" "}{progress.pending_ocr} נוספו לתור OCR, {progress.errors} שגיאות.
          </div>
        )}
      </section>
    </div>
  );
}
