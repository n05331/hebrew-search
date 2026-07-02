import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// אשף אימון מודל Tesseract לפי גופן: בוחרים גופן/ים, רמת הרעשה ושם -
// והתוכנה עושה הכל לבד (רינדור, אימון, אימות) עם מד התקדמות.
export default function FontTraining({ onToast, onModelsChanged }) {
  const [env, setEnv] = useState(null);
  const [fonts, setFonts] = useState([]);
  const [models, setModels] = useState([]);
  const [selected, setSelected] = useState([]);
  const [name, setName] = useState("");
  const [noise, setNoise] = useState("medium");
  const [quality, setQuality] = useState("standard");
  const [st, setSt] = useState(null);
  const pollRef = useRef(null);

  function refreshModels() {
    api.trainingModels().then((r) => setModels(r.models)).catch(() => {});
  }

  useEffect(() => {
    api.trainingCheck().then(setEnv).catch(() => {});
    api.trainingFonts().then((r) => setFonts(r.fonts)).catch(() => {});
    api.trainingStatus().then((s) => {
      setSt(s);
      if (s.running) poll();
    }).catch(() => {});
    refreshModels();
    return () => pollRef.current && clearInterval(pollRef.current);
  }, []);

  function poll() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.trainingStatus();
        setSt(s);
        if (!s.running) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          refreshModels();
          onModelsChanged && onModelsChanged();
          if (s.error) onToast("האימון נכשל: " + s.error, "error");
          else if (s.result) {
            onToast(
              `האימון הושלם! דיוק בגופן: ${s.result.base_score}% במודל הרגיל ← ${s.result.new_score}% במודל החדש`,
              "ok"
            );
          }
        }
      } catch (e) {}
    }, 2000);
  }

  function toggleFont(path) {
    setSelected((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]
    );
  }

  async function start() {
    if (selected.length === 0) { onToast("בחרו לפחות גופן אחד", "error"); return; }
    if (!name.trim()) { onToast("תנו שם למודל (באנגלית)", "error"); return; }
    const params = quality === "fast"
      ? { lines: 200, iterations: 300 }
      : quality === "deep"
        ? { lines: 800, iterations: 1500 }
        : { lines: 400, iterations: 600 };
    try {
      await api.trainingStart({ font_paths: selected, name: name.trim(), noise, ...params });
      setSt({ running: true, step: "מתחיל", percent: 0, error: "" });
      poll();
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function deleteModel(m) {
    if (!window.confirm(`למחוק את המודל "${m}"?`)) return;
    try {
      await api.trainingDeleteModel(m);
      refreshModels();
      onModelsChanged && onModelsChanged();
      onToast("המודל נמחק", "ok");
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  if (env && !env.ok) {
    return (
      <div className="muted">
        אימון מודלים אינו זמין: {env.problems.join("; ")}
      </div>
    );
  }

  const running = st && st.running;

  return (
    <div className="font-training">
      <div className="muted" style={{ marginBottom: 8 }}>
        אימון מודל זיהוי מותאם לגופן: בחרו גופן שדומה לחומר הסרוק שלכם, והתוכנה
        תיצור דפי תרגול מלאכותיים ותאמן עליהם את מנוע Tesseract. בסיום המודל
        יופיע ברשימת "מודל שפה" למעלה.
      </div>

      {!running && (
        <>
          <div className="setting-row">
            <label>גופנים עבריים מותקנים ({fonts.length})</label>
            <div style={{ maxHeight: 180, overflowY: "auto", border: "1px solid var(--border, #ccc)", borderRadius: 6, padding: 6, minWidth: 260 }}>
              {fonts.map((f) => (
                <label key={f.path} className="chk" style={{ display: "block", fontFamily: f.family }}>
                  <input
                    type="checkbox"
                    checked={selected.includes(f.path)}
                    onChange={() => toggleFont(f.path)}
                  />
                  {" "}{f.family} <span className="muted">אבגד שלום</span>
                </label>
              ))}
              {fonts.length === 0 && <span className="muted">לא נמצאו גופנים עבריים</span>}
            </div>
          </div>

          <div className="setting-row">
            <label>שם המודל (אותיות אנגליות)</label>
            <input
              type="text" placeholder="למשל: vilna_print" dir="ltr"
              value={name} onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="setting-row">
            <label title="כמה 'ללכלך' את דפי התרגול - כמו איכות הסריקות שלכם">רמת רעש (איכות סריקה מדומה)</label>
            <select value={noise} onChange={(e) => setNoise(e.target.value)}>
              <option value="low">קלה — סריקות נקיות</option>
              <option value="medium">בינונית — סריקות רגילות</option>
              <option value="high">חזקה — סריקות ישנות/צילומים</option>
            </select>
          </div>

          <div className="setting-row">
            <label>עומק האימון</label>
            <select value={quality} onChange={(e) => setQuality(e.target.value)}>
              <option value="fast">מהיר (~10 דקות)</option>
              <option value="standard">רגיל (~20 דקות)</option>
              <option value="deep">מעמיק (~שעה)</option>
            </select>
          </div>

          <div className="index-actions">
            <button className="btn btn-primary" onClick={start}>התחל אימון</button>
          </div>
        </>
      )}

      {running && (
        <div className="setting-row">
          <label>אימון רץ…</label>
          <div className="setting-inline" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <span>{st.step}{st.detail ? ` — ${st.detail}` : ""}</span>
            <progress value={st.percent || 0} max="100" style={{ width: "100%" }} />
            <button className="btn btn-danger" onClick={() => api.trainingCancel()}>בטל אימון</button>
          </div>
        </div>
      )}

      {!running && st && st.result && !st.error && (
        <div className="index-summary">
          המודל "{st.result.name}" מוכן: דיוק בגופן שנבחר {st.result.base_score}% במודל
          הרגיל ← {st.result.new_score}% במודל החדש.
          בחרו אותו למעלה תחת "מודל שפה" ושמרו.
        </div>
      )}

      {models.length > 0 && !running && (
        <div className="setting-row">
          <label>מודלים מאומנים</label>
          <div>
            {models.map((m) => (
              <div key={m.name} className="folder-row">
                <span className="folder-path" dir="ltr">{m.name}</span>
                <button className="icon-btn" title="מחק" onClick={() => deleteModel(m.name)}>✕</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
