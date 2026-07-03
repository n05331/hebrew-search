import React, { useEffect, useRef, useState } from "react";
import { api, pickSaveFile } from "../api.js";

// חלון "חלץ טקסט" מקובץ PDF: בחירת מקור הטקסט (OCR שמור מהאינדקס /
// שכבת הטקסט / סריקת OCR מחדש במנוע נבחר), טווח עמודים ופורמט.
// הייצוא רץ בשרת כמשימת רקע עם התקדמות "עמוד X מתוך Y" וניתן לביטול;
// התוצאה נשמרת בנתיב שנבחר בדיאלוג "שמירה בשם" נייטיבי.
const SOURCE_LABELS = {
  saved: "הטקסט השמור באינדקס (כולל OCR שכבר בוצע) — מיידי",
  text: "שכבת הטקסט של ה-PDF (חילוץ חכם) — מהיר, בלי OCR",
  ocr: "סריקת OCR מחדש — איטי, מתאים לקבצים סרוקים",
};

export default function ExportDialog({ book, currentPage, totalPages, onClose, onToast }) {
  const [engines, setEngines] = useState([]);
  const [info, setInfo] = useState(null);
  const [source, setSource] = useState("saved");
  const [engine, setEngine] = useState("");
  const [format, setFormat] = useState("txt");
  const [range, setRange] = useState("all"); // all / current / custom
  const [from, setFrom] = useState(currentPage || 1);
  const [to, setTo] = useState(currentPage || 1);
  const [job, setJob] = useState(null);
  const pollRef = useRef(null);
  const targetRef = useRef("");

  useEffect(() => {
    api.ocrEngines().then((r) => setEngines(r.engines.filter((e) => e.available))).catch(() => {});
    api.getSettings()
      .then((r) => setEngine(r.settings.ocr_export_engine || "tesseract"))
      .catch(() => {});
    api.fileInfo(book.pdf_path)
      .then((r) => {
        setInfo(r);
        if (!r.has_text) setSource("text");
      })
      .catch(() => setInfo({ indexed: false }));
    return () => pollRef.current && clearInterval(pollRef.current);
  }, [book.pdf_path]);

  function pageParams() {
    if (range === "current") return { page_from: currentPage || 1, page_to: currentPage || 1 };
    if (range === "custom") return { page_from: from, page_to: to };
    return { page_from: 0, page_to: 0 };
  }

  async function start() {
    const defaultName = book.name + (format === "docx" ? ".docx" : ".txt");
    let target = "";
    try {
      target = (await pickSaveFile(defaultName, format)) || "";
    } catch (e) {}
    if (!target && format === "docx") {
      onToast && onToast("לא נבחר מיקום שמירה", "error");
      return;
    }
    targetRef.current = target;
    try {
      await api.exportExtractStart({
        path: book.pdf_path,
        target,
        source,
        engine: source === "ocr" ? engine : "",
        format,
        ...pageParams(),
      });
    } catch (e) {
      onToast && onToast(e.message, "error");
      return;
    }
    setJob({ running: true, page: 0, pages: 0 });
    pollRef.current = setInterval(async () => {
      try {
        const st = await api.exportExtractStatus();
        setJob(st);
        if (st.running) return;
        clearInterval(pollRef.current);
        pollRef.current = null;
        if (st.error) {
          onToast && onToast(st.error, "error");
          setJob(null);
        } else if (st.done && targetRef.current) {
          onToast && onToast("הטקסט נשמר: " + (st.target || targetRef.current), "ok");
          onClose();
        } else if (st.done && st.result_available) {
          await api.exportExtractResult(`${book.name}.txt`);
          onToast && onToast("הטקסט חולץ והורד", "ok");
          onClose();
        }
      } catch (e) {}
    }, 800);
  }

  async function cancelJob() {
    try { await api.exportExtractCancel(); } catch (e) {}
  }

  const running = job && job.running;

  return (
    <div className="modal-overlay" onClick={running ? undefined : onClose}>
      <div className="modal export-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="doc-name">חילוץ טקסט — {book.name}</span>
          </div>
          <div className="modal-actions">
            <button className="btn btn-sm" onClick={onClose} disabled={running}>✕</button>
          </div>
        </div>
        <div className="modal-body">
          {running ? (
            <div className="export-progress">
              <div>
                {source === "ocr" ? "סורק OCR" : "מחלץ טקסט"}
                {job.pages ? ` — עמוד ${job.page} מתוך ${job.pages}` : "…"}
              </div>
              <progress value={job.page || 0} max={job.pages || 1} style={{ width: "100%" }} />
              <button className="btn" onClick={cancelJob}>בטל</button>
            </div>
          ) : (
            <>
              <div className="setting-row">
                <label>מקור הטקסט</label>
                <div className="export-options">
                  {["saved", "text", "ocr"].map((s) => (
                    <label className="chk" key={s} title={SOURCE_LABELS[s]}>
                      <input
                        type="radio"
                        name="exp-source"
                        checked={source === s}
                        disabled={s === "saved" && info && !info.has_text}
                        onChange={() => setSource(s)}
                      />
                      {" "}{SOURCE_LABELS[s]}
                      {s === "saved" && info && !info.has_text ? " (אין טקסט שמור לקובץ זה)" : ""}
                    </label>
                  ))}
                </div>
              </div>

              {source === "ocr" && engines.length > 1 && (
                <div className="setting-row">
                  <label>מנוע OCR</label>
                  <select value={engine} onChange={(e) => setEngine(e.target.value)}>
                    {engines.map((e) => (
                      <option key={e.id} value={e.id}>{e.label}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className="setting-row">
                <label>עמודים</label>
                <div className="export-options">
                  <label className="chk">
                    <input type="radio" name="exp-range" checked={range === "all"} onChange={() => setRange("all")} />
                    {" "}כל הקובץ{totalPages ? ` (${totalPages} עמודים)` : ""}
                  </label>
                  <label className="chk">
                    <input type="radio" name="exp-range" checked={range === "current"} onChange={() => setRange("current")} />
                    {" "}העמוד הנוכחי ({currentPage || 1})
                  </label>
                  <label className="chk">
                    <input type="radio" name="exp-range" checked={range === "custom"} onChange={() => setRange("custom")} />
                    {" "}טווח:{" "}
                    <input
                      type="number" min={1} max={totalPages || 9999} value={from}
                      style={{ width: 64 }} disabled={range !== "custom"}
                      onChange={(e) => setFrom(parseInt(e.target.value || "1", 10))}
                    />
                    {" "}עד{" "}
                    <input
                      type="number" min={1} max={totalPages || 9999} value={to}
                      style={{ width: 64 }} disabled={range !== "custom"}
                      onChange={(e) => setTo(parseInt(e.target.value || "1", 10))}
                    />
                  </label>
                </div>
              </div>

              <div className="setting-row">
                <label>פורמט</label>
                <div className="export-options">
                  <label className="chk">
                    <input type="radio" name="exp-fmt" checked={format === "txt"} onChange={() => setFormat("txt")} />
                    {" "}קובץ טקסט (TXT)
                  </label>
                  <label className="chk">
                    <input type="radio" name="exp-fmt" checked={format === "docx"} onChange={() => setFormat("docx")} />
                    {" "}קובץ Word‏ (DOCX)
                  </label>
                </div>
              </div>

              {source === "ocr" && (
                <div className="muted" style={{ fontSize: "0.9em" }}>
                  סריקת OCR עשויה לקחת זמן רב (תלוי במנוע ובמספר העמודים). ההתקדמות תוצג כאן וניתן לבטל.
                </div>
              )}

              <div className="index-actions" style={{ marginTop: 14 }}>
                <button className="btn btn-primary" onClick={start}>בחר מיקום והתחל</button>
                <button className="btn" onClick={onClose}>ביטול</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
