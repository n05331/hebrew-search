import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import * as pdfjsLib from "pdfjs-dist";
import PdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { api } from "../api.js";
import OcrResultPanel from "./OcrResultPanel.jsx";

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker;

// מציג PDF מקורי (canvas) בגלילה רציפה עם רינדור עצל: רק העמודים הנראים
// (± חוצץ) מרונדרים, השאר placeholders בגובה משוער - כך גם ספר של 1000
// עמודים נגלל בחלקות. קיים גם מצב "עמוד בודד/כפול" (הדפדוף הקודם).
// זום: כפתורים או Ctrl+גלגלת (ממוקד לסמן); גרירה עם העכבר מזיזה את המסמך;
// "חלץ טקסט מאזור" מאפשר לגרור מלבן על עמוד ולקבל OCR של הקטע.
//
// ref API: scrollToPage(n)

const GAP = 12; // רווח בין עמודים בגלילה

function PageSlot({ pdf, pageNum, width, height, shouldRender, scale, selection }) {
  const canvasRef = useRef(null);
  const taskRef = useRef(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!shouldRender || !pdf) {
      setDone(false);
      return;
    }
    pdf
      .getPage(pageNum)
      .then((pg) => {
        if (cancelled || !canvasRef.current) return;
        const viewport = pg.getViewport({ scale });
        const canvas = canvasRef.current;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const task = pg.render({ canvasContext: canvas.getContext("2d"), viewport });
        taskRef.current = task;
        task.promise.then(() => !cancelled && setDone(true)).catch(() => {});
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      if (taskRef.current) {
        try { taskRef.current.cancel(); } catch (e) {}
        taskRef.current = null;
      }
    };
  }, [pdf, pageNum, shouldRender, scale]);

  return (
    <div
      className="pdf-page-slot"
      data-page={pageNum}
      style={{ width, height, marginBottom: GAP }}
    >
      {shouldRender ? (
        <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
      ) : (
        <div className="pdf-page-placeholder">{pageNum}</div>
      )}
      {shouldRender && !done && <div className="pdf-page-loading">טוען עמוד {pageNum}…</div>}
      {selection && (
        <div
          className="select-rect"
          style={{ left: selection.x, top: selection.y, width: selection.w, height: selection.h }}
        />
      )}
    </div>
  );
}

const PdfViewer = forwardRef(function PdfViewer(
  { path, initialPage = 1, onPageChange, onTotalPages, onUserScroll, onToast },
  ref
) {
  const wrapRef = useRef(null);
  const pdfRef = useRef(null);
  const [pdf, setPdf] = useState(null);
  const [total, setTotal] = useState(0);
  const [zoom, setZoom] = useState(1.0); // מכפיל על התאמה-לרוחב
  const [baseSize, setBaseSize] = useState(null); // {w,h} בגודל scale=1
  const [containerW, setContainerW] = useState(800);
  const [curPage, setCurPage] = useState(initialPage);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const pendingScrollRef = useRef(initialPage > 1 ? initialPage : null);
  const curPageRef = useRef(initialPage);
  const zoomAnchorRef = useRef(null); // {cx, cy, ratio} לשמירת נקודת העוגן בזום
  const panRef = useRef(null);        // {x, y, sl, st} בזמן גרירת המסמך

  // בחירת אזור ל-OCR
  const [regionMode, setRegionMode] = useState(false);
  const [selection, setSelection] = useState(null); // {page, x, y, w, h}
  const [regionBusy, setRegionBusy] = useState(false);
  const [ocrText, setOcrText] = useState(null);
  const selStartRef = useRef(null); // {page, x, y}

  // טעינת המסמך
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPdf(null);
    pdfjsLib
      .getDocument(api.fileUrl(path))
      .promise.then(async (doc) => {
        if (cancelled) return;
        pdfRef.current = doc;
        const pg1 = await doc.getPage(1);
        if (cancelled) return;
        const vp = pg1.getViewport({ scale: 1 });
        setBaseSize({ w: vp.width, h: vp.height });
        setTotal(doc.numPages);
        onTotalPages && onTotalPages(doc.numPages);
        setPdf(doc);
        setLoading(false);
      })
      .catch((e) => {
        if (!cancelled) {
          setError("טעינת ה-PDF נכשלה: " + e.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
      if (pdfRef.current) {
        pdfRef.current.destroy().catch(() => {});
        pdfRef.current = null;
      }
    };
  }, [path]);

  // רוחב הקונטיינר (להתאמת עמוד לרוחב)
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setContainerW(Math.max(200, el.clientWidth - 28));
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const [twoUp, setTwoUp] = useState(false);
  const perRow = twoUp ? 2 : 1;
  const availW = twoUp ? (containerW - GAP) / 2 : containerW;
  const pageW = baseSize ? Math.min(availW, Math.round(baseSize.w * 1.6)) * zoom : 600;
  const scale = baseSize ? pageW / baseSize.w : 1.3;
  const pageH = baseSize ? Math.round(baseSize.h * scale) : 800;

  // שינוי זום עם שמירת נקודת העוגן (ברירת מחדל: מרכז התצוגה)
  const applyZoom = useCallback((factor, cx = null, cy = null) => {
    const el = wrapRef.current;
    setZoom((z) => {
      const nz = Math.min(3, Math.max(0.4, +(z * factor).toFixed(3)));
      if (nz !== z && el) {
        zoomAnchorRef.current = {
          cx: cx != null ? cx : el.clientWidth / 2,
          cy: cy != null ? cy : el.clientHeight / 2,
          ratio: nz / z,
        };
      }
      return nz;
    });
  }, []);

  // אחרי שהמידות התעדכנו - מתקנים את הגלילה כך שנקודת העוגן תישאר במקום
  useLayoutEffect(() => {
    const a = zoomAnchorRef.current;
    const el = wrapRef.current;
    if (!a || !el) return;
    zoomAnchorRef.current = null;
    el.scrollTop = (el.scrollTop + a.cy) * a.ratio - a.cy;
    el.scrollLeft = (el.scrollLeft + a.cx) * a.ratio - a.cx;
  }, [zoom]);

  // Ctrl+גלגלת לזום - מאזין לא-פסיבי כדי לחסום את הגלילה הרגילה
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    function onWheel(e) {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const bounds = el.getBoundingClientRect();
      applyZoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - bounds.left, e.clientY - bounds.top);
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [applyZoom]);

  const scrollToPage = useCallback(
    (n) => {
      const el = wrapRef.current;
      if (!el || !total) return;
      const target = Math.min(Math.max(1, n), total);
      const row = Math.floor((target - 1) / perRow);
      el.scrollTop = row * (pageH + GAP) + 2;
      setCurPage(target);
      curPageRef.current = target;
    },
    [total, pageH, perRow]
  );

  useImperativeHandle(ref, () => ({ scrollToPage }), [scrollToPage]);

  // קפיצה לעמוד ההתחלתי אחרי שנקבעו מידות
  useLayoutEffect(() => {
    if (pdf && baseSize && pendingScrollRef.current) {
      const n = pendingScrollRef.current;
      pendingScrollRef.current = null;
      requestAnimationFrame(() => scrollToPage(n));
    }
  }, [pdf, baseSize, scrollToPage]);

  function onScroll() {
    const el = wrapRef.current;
    if (!el) return;
    onUserScroll && onUserScroll();
    const row = Math.floor(el.scrollTop / (pageH + GAP));
    const p = Math.min(total, Math.max(1, row * perRow + 1));
    if (p !== curPageRef.current) {
      curPageRef.current = p;
      setCurPage(p);
      onPageChange && onPageChange(p, total);
    }
  }

  useEffect(() => {
    if (total) onPageChange && onPageChange(curPageRef.current, total);
  }, [total]);

  // ---- בחירת אזור ל-OCR וגרירת המסמך ----
  function findSlot(e) {
    const slot = e.target.closest && e.target.closest(".pdf-page-slot");
    if (!slot) return null;
    const bounds = slot.getBoundingClientRect();
    return {
      page: parseInt(slot.dataset.page, 10),
      x: Math.min(Math.max(0, e.clientX - bounds.left), bounds.width),
      y: Math.min(Math.max(0, e.clientY - bounds.top), bounds.height),
      bw: bounds.width,
      bh: bounds.height,
    };
  }

  function onMouseDown(e) {
    if (regionMode) {
      const p = findSlot(e);
      if (!p) return;
      e.preventDefault();
      selStartRef.current = p;
      setSelection({ page: p.page, x: p.x, y: p.y, w: 0, h: 0 });
      return;
    }
    // גרירת המסמך (pan)
    if (e.button !== 0) return;
    const el = wrapRef.current;
    panRef.current = { x: e.clientX, y: e.clientY, sl: el.scrollLeft, st: el.scrollTop };
  }

  function onMouseMove(e) {
    if (regionMode) {
      const start = selStartRef.current;
      if (!start) return;
      const slot = wrapRef.current.querySelector(`.pdf-page-slot[data-page="${start.page}"]`);
      if (!slot) return;
      const bounds = slot.getBoundingClientRect();
      const x = Math.min(Math.max(0, e.clientX - bounds.left), bounds.width);
      const y = Math.min(Math.max(0, e.clientY - bounds.top), bounds.height);
      setSelection({
        page: start.page,
        x: Math.min(start.x, x),
        y: Math.min(start.y, y),
        w: Math.abs(x - start.x),
        h: Math.abs(y - start.y),
      });
      return;
    }
    if (panRef.current) {
      const el = wrapRef.current;
      el.scrollLeft = panRef.current.sl - (e.clientX - panRef.current.x);
      el.scrollTop = panRef.current.st - (e.clientY - panRef.current.y);
    }
  }

  async function onMouseUp() {
    if (!regionMode) {
      panRef.current = null;
      return;
    }
    const start = selStartRef.current;
    const sel = selection;
    selStartRef.current = null;
    if (!start || !sel || sel.w < 8 || sel.h < 8) return;

    setRegionBusy(true);
    try {
      const r = await api.ocrRegion(
        path, sel.x / pageW, sel.y / pageH, sel.w / pageW, sel.h / pageH, sel.page
      );
      setOcrText(r.text || "(לא זוהה טקסט באזור שנבחר)");
      setRegionMode(false);
      setSelection(null);
    } catch (e2) {
      onToast && onToast("חילוץ הטקסט נכשל: " + e2.message, "error");
    } finally {
      setRegionBusy(false);
    }
  }

  const BUFFER = twoUp ? 4 : 2;
  const slots = [];
  for (let i = 1; i <= total; i++) {
    slots.push(
      <PageSlot
        key={i}
        pdf={pdf}
        pageNum={i}
        width={pageW}
        height={pageH}
        scale={scale}
        shouldRender={Math.abs(i - curPage) <= BUFFER}
        selection={regionMode && selection && selection.page === i ? selection : null}
      />
    );
  }
  // במצב שני עמודים: זוגות (1,2)(3,4) - העמוד הנמוך מימין (RTL)
  let pages;
  if (twoUp) {
    const rows = [];
    for (let i = 0; i < slots.length; i += 2) {
      rows.push(
        <div className="pdf-row-two" key={"r" + i} style={{ marginBottom: 0 }}>
          {slots[i]}
          {slots[i + 1] || <div style={{ width: pageW }} />}
        </div>
      );
    }
    pages = rows;
  } else {
    pages = slots;
  }

  const baseName = (path.split(/[\\/]/).pop() || "pdf").replace(/\.[^.]+$/, "");

  return (
    <div className="pdf-viewer">
      <div className="pdf-toolbar">
        <button className="btn btn-sm" onClick={() => scrollToPage(1)} title="עמוד ראשון">⏮</button>
        <button className="btn btn-sm" onClick={() => scrollToPage(curPage - 1)} title="קודם">‹</button>
        <span className="pdf-page-info">
          עמוד{" "}
          <input
            className="pdf-page-input"
            type="number"
            value={curPage}
            min={1}
            max={total || 1}
            onChange={(e) => {
              const v = parseInt(e.target.value || "1", 10);
              if (!isNaN(v)) scrollToPage(v);
            }}
          />{" "}
          מתוך {total}
        </span>
        <button className="btn btn-sm" onClick={() => scrollToPage(curPage + 1)} title="הבא">›</button>
        <button className="btn btn-sm" onClick={() => scrollToPage(total)} title="עמוד אחרון">⏭</button>
        <span className="toolbar-sep" />
        <button className="btn btn-sm" onClick={() => applyZoom(1.15)} title="הגדלה (או Ctrl+גלגלת)">+</button>
        <button className="btn btn-sm" onClick={() => applyZoom(1 / 1.15)} title="הקטנה (או Ctrl+גלגלת)">−</button>
        <span className="muted pdf-zoom-label">{Math.round(zoom * 100)}%</span>
        <span className="toolbar-sep" />
        <button
          className={"btn btn-sm" + (regionMode ? " btn-primary" : "")}
          onClick={() => { setRegionMode((v) => !v); setSelection(null); }}
          title="גררו מלבן על עמוד לזיהוי הטקסט שבו (OCR)"
        >
          {regionMode ? "גררו מלבן על העמוד…" : "חלץ טקסט מאזור"}
        </button>
        {regionBusy && <span className="muted">מזהה טקסט…</span>}
        <span className="toolbar-sep" />
        <button
          className={"btn btn-sm" + (twoUp ? " btn-primary" : "")}
          onClick={() => setTwoUp((v) => !v)}
          title="תצוגת שני עמודים זה לצד זה"
        >
          {twoUp ? "עמוד אחד" : "שני עמודים"}
        </button>
      </div>
      <div
        className={"pdf-scroll-wrap" + (regionMode ? " selecting" : " pannable")}
        ref={wrapRef}
        onScroll={onScroll}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={() => { panRef.current = null; }}
      >
        {loading && <div className="loading">טוען PDF…</div>}
        {error && <div className="error-box">{error}</div>}
        {pdf && <div className="pdf-pages-scroll">{pages}</div>}
      </div>
      {ocrText != null && (
        <div className="pdf-ocr-float">
          <OcrResultPanel
            text={ocrText}
            baseName={baseName}
            onClose={() => setOcrText(null)}
            onToast={onToast}
          />
        </div>
      )}
    </div>
  );
});

export default PdfViewer;
