import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import FontTraining from "./FontTraining.jsx";

// סעיף הגדרות "זיהוי טקסט (OCR)": בחירת מנוע ופאנל הגדרות דינמי לפי
// הסכימה שהשרת מחזיר - מנוע חדש ב-backend מופיע כאן ללא שינוי קוד.
export default function OcrSettings({ local, edit, onToast }) {
  const [engines, setEngines] = useState([]);
  const [rerunBusy, setRerunBusy] = useState(false);
  const [surya, setSurya] = useState(null);
  const pollRef = useRef(null);

  function refreshEngines() {
    api.ocrEngines().then((r) => setEngines(r.engines)).catch(() => {});
  }

  useEffect(() => {
    refreshEngines();
    api.suryaStatus().then(setSurya).catch(() => {});
    return () => pollRef.current && clearInterval(pollRef.current);
  }, []);

  function pollSurya() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.suryaStatus();
        setSurya(s);
        if (!s.running) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          refreshEngines();
          if (s.error) onToast("התקנת Surya נכשלה: " + s.error, "error");
          else if (s.installed) onToast("מנוע Surya הותקן בהצלחה", "ok");
        }
      } catch (e) {}
    }, 1500);
  }

  async function installSurya() {
    if (!window.confirm(
      "התקנת מנוע Surya מורידה כ-3GB (סביבת Python, PyTorch והמודל).\n" +
      "בהרצה הראשונה יורדו מודלים נוספים. להמשיך?"
    )) return;
    try {
      await api.suryaInstall();
      setSurya((s) => ({ ...(s || {}), running: true, step: "מתחיל", percent: 0, error: "" }));
      pollSurya();
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function toggleSuryaGpu(enable) {
    if (!enable) {
      edit({ ocr_surya_gpu: "0" });
      return;
    }
    if (!window.confirm(
      "האצה ב-GPU משולב (Vulkan) — ניסיוני:\n\n" +
      "• עשוי להאיץ את הזיהוי במחשבים ללא כרטיס NVIDIA, בעיקר את עיבוד התמונה.\n" +
      "• במחשבים מסוימים המנוע קורס במצב זה — במקרה כזה התוכנה תזהה את הכשל,\n" +
      "  תחזור אוטומטית למצב מעבד (CPU) ותכבה את ההגדרה.\n" +
      "• בהפעלה ראשונה תורד תוספת של כ-100MB.\n\nלהפעיל?"
    )) return;
    try {
      const r = await api.suryaVulkanInstall();
      if (r.started) {
        setSurya((s) => ({ ...(s || {}), running: true, step: "הורדת רכיב Vulkan", percent: 0, error: "" }));
        pollSurya();
      }
      edit({ ocr_surya_gpu: "1" });
      onToast("הופעל מצב GPU משולב — זכרו לשמור הגדרות", "ok");
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function uninstallSurya() {
    if (!window.confirm("להסיר את מנוע Surya מהמחשב? (ניתן להתקין שוב בכל עת)")) return;
    try {
      await api.suryaUninstall();
      const s = await api.suryaStatus();
      setSurya(s);
      refreshEngines();
      if (local.ocr_engine === "surya") edit({ ocr_engine: "tesseract" });
      onToast("מנוע Surya הוסר", "ok");
    } catch (e) {
      onToast(e.message, "error");
    }
  }

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

      {surya && (
        <div className="setting-row">
          <label>מנוע Surya (דיוק גבוה בעברית)</label>
          <div className="setting-inline" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            {surya.installed && !surya.running && (
              <>
                <span>מותקן ✓ {surya.nvidia ? "(כרטיס NVIDIA זוהה)" : "(ללא NVIDIA - הזיהוי איטי: מספר דקות לעמוד)"}</span>
                {!surya.nvidia && (
                  <label className="chk" title="ניסיוני - עם חזרה אוטומטית ל-CPU בכשל">
                    <input
                      type="checkbox"
                      checked={String(local.ocr_surya_gpu || "0") === "1"}
                      onChange={(e) => toggleSuryaGpu(e.target.checked)}
                    />
                    {" "}האצה ב-GPU משולב (Vulkan) — ניסיוני
                  </label>
                )}
                <button className="btn" onClick={uninstallSurya}>הסר את המנוע</button>
              </>
            )}
            {!surya.installed && !surya.running && (
              <>
                <span className="muted">
                  מנוע זיהוי מדויק במיוחד לעברית, מזהה עמודות ופריסת עמוד (מתאים לעלונים).
                  דורש הורדה של כ-3GB{surya.nvidia ? "" : "; ללא כרטיס NVIDIA הזיהוי איטי מאוד (מספר דקות לעמוד)"}.
                  למחשב ללא אינטרנט: השתמשו ב"ייצוא וייבוא" בהמשך העמוד.
                </span>
                <button className="btn btn-primary" onClick={installSurya}>התקן את מנוע Surya</button>
                {surya.error && <span className="muted" style={{ color: "var(--danger, #c00)" }}>שגיאה קודמת: {surya.error}</span>}
              </>
            )}
            {surya.running && (
              <>
                <span>{surya.step}{surya.detail ? ` — ${surya.detail}` : ""}</span>
                <progress value={surya.percent || 0} max="100" style={{ width: "100%" }} />
              </>
            )}
          </div>
        </div>
      )}

      <details style={{ marginTop: 10 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>
          אימון מודל זיהוי מותאם לפי גופן
        </summary>
        <div style={{ marginTop: 8 }}>
          <FontTraining onToast={onToast} onModelsChanged={refreshEngines} />
        </div>
      </details>

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
