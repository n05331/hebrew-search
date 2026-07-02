import React, { useEffect, useRef, useState } from "react";
import { api, pickFolder, pickOpenFile } from "../api.js";

const COMPONENT_LABELS = {
  settings: "הגדרות ותיקיות מקור",
  index: "אינדקס החיפוש (טקסטים שחולצו, כולל OCR)",
  models: "מודלים מאומנים (אשף הגופנים)",
  surya: "מנוע Surya (להתקנת אופליין, ~2.5GB)",
};

// ייצוא/ייבוא נתוני התוכנה: בוחרים רכיבים, הכל נארז לקובץ אחד.
// ביבוא של אינדקס - קבצים שקיימים בדיסק זמינים מיד, וקבצים שאינם קיימים
// נשמרים כמטמון לפי תוכן וייתפסו אוטומטית כשהקבצים יתווספו מכל מיקום.
export default function TransferSettings({ onToast }) {
  const [avail, setAvail] = useState(null);
  const [exportSel, setExportSel] = useState({ settings: true, index: true, models: true, surya: false });
  const [st, setSt] = useState(null);
  const [importFile, setImportFile] = useState("");
  const [importManifest, setImportManifest] = useState(null);
  const [importSel, setImportSel] = useState({});
  const pollRef = useRef(null);

  useEffect(() => {
    api.transferComponents().then((r) => setAvail(r.components)).catch(() => {});
    api.transferStatus().then((s) => {
      setSt(s);
      if (s.running) poll();
    }).catch(() => {});
    return () => pollRef.current && clearInterval(pollRef.current);
  }, []);

  function poll() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.transferStatus();
        setSt(s);
        if (!s.running) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          if (s.error) onToast(`ה${s.op === "export" ? "ייצוא" : "ייבוא"} נכשל: ${s.error}`, "error");
          else if (s.op === "export") onToast("הייצוא הושלם: " + ((s.result || {}).target || ""), "ok");
          else {
            const r = s.result || {};
            const parts = [];
            if (r.index) parts.push(`אינדקס: ${r.index.indexed} קבצים זמינים + ${r.index.cached} במטמון תוכן`);
            if (r.models && r.models.length) parts.push(`מודלים: ${r.models.join(", ")}`);
            if (r.settings) parts.push("הגדרות");
            if (r.surya) parts.push("מנוע Surya");
            onToast("הייבוא הושלם. " + parts.join(" | "), "ok");
            api.transferComponents().then((x) => setAvail(x.components)).catch(() => {});
          }
        }
      } catch (e) {}
    }, 1500);
  }

  async function doExport() {
    const components = Object.keys(exportSel).filter((k) => exportSel[k]);
    if (components.length === 0) { onToast("בחרו לפחות רכיב אחד", "error"); return; }
    let dir = await pickFolder();
    if (!dir) dir = window.prompt("הדביקו נתיב תיקייה לשמירת הקובץ (למשל החסן נייד):", "");
    if (!dir) return;
    try {
      await api.transferExport(dir, components);
      setSt({ running: true, op: "export", step: "מתחיל", percent: 0 });
      poll();
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function chooseImportFile() {
    let file = await pickOpenFile("zip");
    if (!file) file = window.prompt("הדביקו נתיב מלא לקובץ HebrewSearch-Transfer.zip:", "");
    if (!file) return;
    try {
      const r = await api.transferInspect(file);
      const comps = (r.manifest || {}).components || {};
      setImportFile(file);
      setImportManifest(comps);
      const sel = {};
      Object.keys(comps).forEach((k) => { sel[k] = true; });
      setImportSel(sel);
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  async function doImport() {
    const components = Object.keys(importSel).filter((k) => importSel[k]);
    if (components.length === 0) { onToast("בחרו לפחות רכיב אחד", "error"); return; }
    try {
      await api.transferImport(importFile, components);
      setImportFile("");
      setImportManifest(null);
      setSt({ running: true, op: "import", step: "מתחיל", percent: 0 });
      poll();
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  const running = st && st.running;

  function componentInfo(key) {
    if (!avail || !avail[key]) return "";
    if (key === "index" && avail.index.count) return ` (${avail.index.count} קבצים)`;
    if (key === "models" && (avail.models.names || []).length) return ` (${avail.models.names.join(", ")})`;
    return "";
  }

  return (
    <section className="settings-section">
      <h3>ייצוא וייבוא (העברה בין מחשבים / אופליין)</h3>
      <div className="muted" style={{ marginBottom: 8 }}>
        מייצא קובץ אחד עם הרכיבים שנבחרו, לייבוא במחשב אחר - כולל מחשב ללא
        אינטרנט. אינדקס מיובא מזהה קבצים גם לפי תוכן: אם הקבצים יתווספו
        במיקום אחר, הטקסט שלהם (כולל OCR) יזוהה מיד בלי סריקה יקרה מחדש.
      </div>

      {!running && (
        <>
          <div className="setting-row">
            <label>ייצוא — מה לכלול</label>
            <div>
              {Object.keys(COMPONENT_LABELS).map((k) => (
                <label key={k} className="chk" style={{ display: "block" }}>
                  <input
                    type="checkbox"
                    checked={!!exportSel[k]}
                    disabled={avail && avail[k] && !avail[k].available}
                    onChange={(e) => setExportSel((p) => ({ ...p, [k]: e.target.checked }))}
                  />
                  {" "}{COMPONENT_LABELS[k]}{componentInfo(k)}
                  {avail && avail[k] && !avail[k].available && <span className="muted"> — לא זמין</span>}
                </label>
              ))}
              <button className="btn btn-primary" style={{ marginTop: 6 }} onClick={doExport}>
                ייצוא לקובץ…
              </button>
            </div>
          </div>

          <div className="setting-row">
            <label>ייבוא מקובץ</label>
            <div>
              {!importManifest && (
                <button className="btn" onClick={chooseImportFile}>בחירת קובץ…</button>
              )}
              {importManifest && (
                <>
                  <div className="muted" dir="ltr" style={{ marginBottom: 4 }}>{importFile}</div>
                  {Object.keys(importManifest).map((k) => (
                    <label key={k} className="chk" style={{ display: "block" }}>
                      <input
                        type="checkbox"
                        checked={!!importSel[k]}
                        onChange={(e) => setImportSel((p) => ({ ...p, [k]: e.target.checked }))}
                      />
                      {" "}{COMPONENT_LABELS[k] || k}
                      {k === "index" && importManifest.index && importManifest.index.count
                        ? ` (${importManifest.index.count} קבצים)` : ""}
                    </label>
                  ))}
                  <div className="setting-inline" style={{ marginTop: 6 }}>
                    <button className="btn btn-primary" onClick={doImport}>ייבוא</button>
                    <button className="btn" onClick={() => { setImportManifest(null); setImportFile(""); }}>
                      ביטול
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}

      {running && (
        <div className="setting-row">
          <label>{st.op === "export" ? "ייצוא רץ…" : "ייבוא רץ…"}</label>
          <div className="setting-inline" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <span>{st.step}{st.detail ? ` — ${st.detail}` : ""}</span>
            <progress value={st.percent || 0} max="100" style={{ width: "100%" }} />
          </div>
        </div>
      )}
    </section>
  );
}
