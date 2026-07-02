import React, { useRef, useState } from "react";
import { api, copyText, downloadText, pickSaveFile } from "../api.js";

// מציג תמונה עם חילוץ טקסט אזורי: לוחצים "חלץ טקסט", גוררים מלבן על
// התמונה (כמו כלי החיתוך של Windows), והטקסט מוצג בחלונית.
export default function ImageViewer({ path, onToast }) {
  const imgRef = useRef(null);
  const [selectMode, setSelectMode] = useState(false);
  const [rect, setRect] = useState(null); // {x,y,w,h} בפיקסלים של התצוגה
  const [dragStart, setDragStart] = useState(null);
  const [ocrText, setOcrText] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saveMenu, setSaveMenu] = useState(false);

  async function saveAs(format) {
    setSaveMenu(false);
    const baseName = (path.split(/[\\/]/).pop() || "ocr").replace(/\.[^.]+$/, "");
    const defaultName = baseName + (format === "docx" ? ".docx" : ".txt");
    try {
      // דיאלוג "שמירה בשם" נייטיב (בגרסת השולחן); בנפילה - הורדה רגילה
      const target = await pickSaveFile(defaultName, format);
      if (target) {
        await api.saveTextFile(target, ocrText, format);
        onToast && onToast("הקובץ נשמר: " + target, "ok");
      } else if (format === "txt") {
        downloadText(ocrText, defaultName);
      } else {
        onToast && onToast("לא נבחר מיקום שמירה", "error");
      }
    } catch (e) {
      onToast && onToast("השמירה נכשלה: " + e.message, "error");
    }
  }

  function relPos(e) {
    const bounds = imgRef.current.getBoundingClientRect();
    return {
      x: Math.min(Math.max(0, e.clientX - bounds.left), bounds.width),
      y: Math.min(Math.max(0, e.clientY - bounds.top), bounds.height),
      bw: bounds.width,
      bh: bounds.height,
    };
  }

  function onMouseDown(e) {
    if (!selectMode) return;
    e.preventDefault();
    const p = relPos(e);
    setDragStart(p);
    setRect({ x: p.x, y: p.y, w: 0, h: 0 });
  }

  function onMouseMove(e) {
    if (!selectMode || !dragStart) return;
    const p = relPos(e);
    setRect({
      x: Math.min(dragStart.x, p.x),
      y: Math.min(dragStart.y, p.y),
      w: Math.abs(p.x - dragStart.x),
      h: Math.abs(p.y - dragStart.y),
    });
  }

  async function onMouseUp(e) {
    if (!selectMode || !dragStart || !rect) return;
    const { bw, bh } = relPos(e);
    setDragStart(null);
    if (rect.w < 8 || rect.h < 8) return; // בחירה קטנה מדי

    setBusy(true);
    try {
      const r = await api.ocrRegion(path, rect.x / bw, rect.y / bh, rect.w / bw, rect.h / bh);
      setOcrText(r.text || "(לא זוהה טקסט באזור שנבחר)");
      setSelectMode(false);
    } catch (e2) {
      onToast && onToast("חילוץ הטקסט נכשל: " + e2.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function fullOcr() {
    setBusy(true);
    try {
      const r = await api.ocrRegion(path, 0, 0, 1, 1);
      setOcrText(r.text || "(לא זוהה טקסט)");
    } catch (e) {
      onToast && onToast("חילוץ הטקסט נכשל: " + e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="image-viewer">
      <div className="image-toolbar">
        <button
          className={"btn btn-sm" + (selectMode ? " btn-primary" : "")}
          onClick={() => { setSelectMode((v) => !v); setRect(null); }}
        >
          {selectMode ? "גררו מלבן על התמונה…" : "חלץ טקסט מאזור"}
        </button>
        <button className="btn btn-sm" onClick={fullOcr} disabled={busy}>
          חלץ טקסט מכל התמונה
        </button>
        {busy && <span className="muted">מזהה טקסט…</span>}
      </div>

      <div className="image-stage">
        <div
          className={"image-wrap" + (selectMode ? " selecting" : "")}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
        >
          <img ref={imgRef} src={api.fileUrl(path)} alt="" draggable={false} />
          {rect && selectMode && (
            <div
              className="select-rect"
              style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
            />
          )}
        </div>

        {ocrText != null && (
          <div className="ocr-result">
            <div className="ocr-result-head">
              <b>טקסט מחולץ</b>
              <div className="ocr-actions">
                <button
                  className="btn btn-sm"
                  onClick={async () => {
                    const ok = await copyText(ocrText);
                    onToast && onToast(ok ? "הועתק ללוח" : "ההעתקה נכשלה", ok ? "ok" : "error");
                  }}
                >
                  העתק
                </button>
                <button
                  className={"btn btn-sm" + (saveMenu ? " btn-primary" : "")}
                  onClick={() => setSaveMenu((v) => !v)}
                >
                  שמור ▾
                </button>
                <button className="btn btn-sm" onClick={() => { setOcrText(null); setSaveMenu(false); }}>סגור</button>
                {saveMenu && (
                  <div className="save-menu">
                    <button className="btn btn-sm" onClick={() => saveAs("txt")}>שמור כקובץ TXT</button>
                    <button className="btn btn-sm" onClick={() => saveAs("docx")}>שמור כקובץ WORD</button>
                  </div>
                )}
              </div>
            </div>
            <pre className="doc-text ocr-text">{ocrText}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
