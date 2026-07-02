import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// סעיף הגדרות "זיהוי טקסט (OCR)": בחירת מנוע ופאנל הגדרות דינמי לפי
// הסכימה שהשרת מחזיר - מנוע חדש ב-backend מופיע כאן ללא שינוי קוד.
export default function OcrSettings({ local, edit, onToast }) {
  const [engines, setEngines] = useState([]);
  const [rerunBusy, setRerunBusy] = useState(false);

  useEffect(() => {
    api.ocrEngines().then((r) => setEngines(r.engines)).catch(() => {});
  }, []);

  const engineId = local.ocr_engine || "tesseract";
  const engine = engines.find((e) => e.id === engineId) || engines[0];

  async function rerunOcr() {
    if (!window.confirm(
      "כל הקבצים שעברו OCR יחזרו לתור ויעברו זיהוי מחדש עם ההגדרות הנוכחיות.\nהתהליך רץ ברקע ועשוי לקחת זמן. להמשיך?"
    )) return;
    setRerunBusy(true);
    try {
      const r = await api.ocrRerun();
      onToast(`${r.queued} קבצים הוחזרו לתור ה-OCR`, "ok");
    } catch (e) {
      onToast("הפעלת OCR מחדש נכשלה: " + e.message, "error");
    } finally {
      setRerunBusy(false);
    }
  }

  function renderField(f) {
    // שדה תלוי: מוסתר כשההגדרה שהוא תלוי בה כבויה
    if (f.depends && String(local[f.depends] ?? "1") !== "1") return null;
    const value = local[f.key] ?? f.default ?? "";
    return (
      <div className="setting-row" key={f.key}>
        <label title={f.help || ""}>{f.label}</label>
        {f.type === "select" && (
          <select value={value} onChange={(e) => edit({ [f.key]: e.target.value })}>
            {(f.options || []).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        )}
        {f.type === "number" && (
          <input
            type="number" min={f.min} max={f.max} value={value}
            onChange={(e) => edit({ [f.key]: e.target.value })}
          />
        )}
        {f.type === "bool" && (
          <label className="chk">
            <input
              type="checkbox"
              checked={String(value) === "1"}
              onChange={(e) => edit({ [f.key]: e.target.checked ? "1" : "0" })}
            />
            {f.help ? <span className="muted">{f.help}</span> : null}
          </label>
        )}
      </div>
    );
  }

  return (
    <section className="settings-section">
      <h3>זיהוי טקסט (OCR)</h3>

      <div className="setting-row">
        <label>מנוע OCR לאינדוקס</label>
        <select value={engineId} onChange={(e) => edit({ ocr_engine: e.target.value })}>
          {engines.map((e) => (
            <option key={e.id} value={e.id} disabled={!e.available}>
              {e.label}{e.available ? "" : ` — ${e.status}`}
            </option>
          ))}
        </select>
      </div>

      {engines.length > 1 && (
        <div className="setting-row">
          <label title="הזיהוי בלחיצה על אזור בתמונה - כדאי מנוע מהיר">מנוע לזיהוי אזורי (במציג)</label>
          <select
            value={local.ocr_region_engine || "tesseract"}
            onChange={(e) => edit({ ocr_region_engine: e.target.value })}
          >
            {engines.filter((e) => e.available).map((e) => (
              <option key={e.id} value={e.id}>{e.label}</option>
            ))}
          </select>
        </div>
      )}

      {engine && !engine.available && (
        <div className="muted">{engine.label}: {engine.status}</div>
      )}

      {engine && engine.available && (engine.settings || []).map(renderField)}

      <div className="index-actions">
        <button className="btn" onClick={rerunOcr} disabled={rerunBusy}>
          {rerunBusy ? "מפעיל…" : "הרץ OCR מחדש על כל הקבצים"}
        </button>
      </div>
      <div className="muted" style={{ fontSize: "0.85em" }}>
        שינוי מנוע או הגדרות משפיע על קבצים חדשים; לקבצים קיימים השתמשו ב"הרץ OCR מחדש".
        זכרו לשמור הגדרות לפני ההרצה.
      </div>
    </section>
  );
}
