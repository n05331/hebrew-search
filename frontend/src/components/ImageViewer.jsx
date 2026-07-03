import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import OcrResultPanel from "./OcrResultPanel.jsx";

// מציג תמונה עם חילוץ טקסט אזורי: לוחצים "חלץ טקסט", גוררים מלבן על
// התמונה (כמו כלי החיתוך של Windows), והטקסט מוצג בחלונית.
// זום: Ctrl+גלגלת; גרירה עם העכבר מזיזה את התמונה כשהיא מוגדלת.
export default function ImageViewer({ path, onToast }) {
  const wrapRef = useRef(null);
  const imgRef = useRef(null);
  const baseWRef = useRef(null); // רוחב התמונה בזום 1 (נמדד פעם אחת)
  const panRef = useRef(null);   // {x, y, sl, st} בזמן גרירה
  const [zoom, setZoom] = useState(1);
  const [selectMode, setSelectMode] = useState(false);
  const [rect, setRect] = useState(null); // {x,y,w,h} בפיקסלים של התצוגה
  const [dragStart, setDragStart] = useState(null);
  const [ocrText, setOcrText] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setZoom(1);
    baseWRef.current = null;
  }, [path]);

  // זום ב-Ctrl+גלגלת - מאזין לא-פסיבי כדי לחסום את גלילת הדף
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    function onWheel(e) {
      if (!e.ctrlKey) return;
      e.preventDefault();
      if (baseWRef.current == null && imgRef.current) {
        baseWRef.current = imgRef.current.clientWidth;
      }
      setZoom((z) => Math.min(6, Math.max(0.3, +(z * (e.deltaY < 0 ? 1.12 : 1 / 1.12)).toFixed(3))));
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

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
    if (!selectMode) {
      // גרירת התמונה (pan) - הזזת הגלילה של המיכל
      if (e.button !== 0) return;
      const el = wrapRef.current;
      panRef.current = { x: e.clientX, y: e.clientY, sl: el.scrollLeft, st: el.scrollTop };
      e.preventDefault();
      return;
    }
    e.preventDefault();
    const p = relPos(e);
    setDragStart(p);
    setRect({ x: p.x, y: p.y, w: 0, h: 0 });
  }

  function onMouseMove(e) {
    if (!selectMode) {
      if (panRef.current) {
        const el = wrapRef.current;
        el.scrollLeft = panRef.current.sl - (e.clientX - panRef.current.x);
        el.scrollTop = panRef.current.st - (e.clientY - panRef.current.y);
      }
      return;
    }
    if (!dragStart) return;
    const p = relPos(e);
    setRect({
      x: Math.min(dragStart.x, p.x),
      y: Math.min(dragStart.y, p.y),
      w: Math.abs(p.x - dragStart.x),
      h: Math.abs(p.y - dragStart.y),
    });
  }

  async function onMouseUp(e) {
    if (!selectMode) {
      panRef.current = null;
      return;
    }
    if (!dragStart || !rect) return;
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

  const baseName = (path.split(/[\\/]/).pop() || "ocr").replace(/\.[^.]+$/, "");
  const zoomed = zoom !== 1 && baseWRef.current != null;

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
        {zoomed && (
          <>
            <span className="muted">{Math.round(zoom * 100)}%</span>
            <button className="btn btn-sm" onClick={() => setZoom(1)}>איפוס זום</button>
          </>
        )}
        <span className="muted" style={{ fontSize: "0.85em" }}>Ctrl+גלגלת לזום, גרירה להזזה</span>
      </div>

      <div className="image-stage">
        <div
          ref={wrapRef}
          className={"image-wrap" + (selectMode ? " selecting" : " pannable")}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={() => { panRef.current = null; }}
        >
          <div className="image-canvas">
            <img
              ref={imgRef}
              src={api.fileUrl(path)}
              alt=""
              draggable={false}
              style={zoomed ? { width: Math.round(baseWRef.current * zoom), maxWidth: "none" } : undefined}
            />
            {rect && selectMode && (
              <div
                className="select-rect"
                style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
              />
            )}
          </div>
        </div>

        {ocrText != null && (
          <OcrResultPanel
            text={ocrText}
            baseName={baseName}
            onClose={() => setOcrText(null)}
            onToast={onToast}
          />
        )}
      </div>
    </div>
  );
}
