import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import PdfViewer from "./PdfViewer.jsx";
import ImageViewer from "./ImageViewer.jsx";
import TextBookViewer from "./TextBookViewer.jsx";
import TocPanel from "./TocPanel.jsx";
import ExportDialog from "./ExportDialog.jsx";

// מציג ספר: טקסט (גלילה רציפה + כותרות) / PDF (גלילה רציפה, מקורי) / תמונה,
// עם חלונית צד של עץ כותרות + חיפוש-בספר, מעבר טקסט<->PDF לפי כותרות,
// מפרשים וסימניות.
// book = { kind, name, dual, text_path, pdf_path, image_path, mefarshim }

export default function BookViewer({
  book,
  settings,
  initialView,
  initialPosition,
  autoSearchQuery,
  onToast,
  onOpenMefarshim,
  compact,
}) {
  const isDual = !!book.dual;
  const defaultView =
    initialView ||
    (book.kind === "image"
      ? "image"
      : isDual
      ? settings.at_default || "text"
      : book.pdf_path && !book.text_path
      ? "pdf"
      : "text");

  // מיקום התחלתי (מסימנייה / תוצאת חיפוש)
  let initChunk = 0, initOffset = null, initPage = 1;
  if (initialPosition) {
    try {
      const pos = JSON.parse(initialPosition);
      if (pos.chunk != null) initChunk = pos.chunk;
      if (pos.offset != null) initOffset = pos.offset;
      if (pos.page != null) initPage = pos.page;
    } catch (e) {}
  }

  const [view, setView] = useState(defaultView);
  const [fontSize, setFontSize] = useState(parseInt(settings.font_size || "30", 10));
  const [removeNiqqud, setRemoveNiqqud] = useState(false);
  const [removeTeamim, setRemoveTeamim] = useState(false);
  const [meta, setMeta] = useState(null); // has_niqqud / has_teamim / total_chunks

  // עץ כותרות + חיפוש בספר
  const [toc, setToc] = useState(null);
  const [tocOpen, setTocOpen] = useState(false);
  const tocAutoClosedRef = useRef(false);

  // הדגשות חיפוש-בספר (טקסט)
  const [bookHits, setBookHits] = useState(null);
  const [activeHit, setActiveHit] = useState(-1);

  // מיקום נוכחי
  const posRef = useRef({ chunk: initChunk, absOffset: 0 });
  const [pdfPage, setPdfPage] = useState(initPage);
  const [pdfTotal, setPdfTotal] = useState(0);
  const pdfPageRef = useRef(initPage);

  // יעד קפיצה לתצוגת טקסט
  const seqRef = useRef(1);
  const [textTarget, setTextTarget] = useState(
    initChunk || initOffset != null ? { chunk: initChunk, offset: initOffset, seq: 0 } : null
  );

  const textRef = useRef(null);
  const pdfRef = useRef(null);

  useEffect(() => {
    setFontSize(parseInt(settings.font_size || "30", 10));
  }, [settings.font_size]);

  // איפוס בהחלפת ספר (לפי נתיב יציב - לא לפי זהות האובייקט, שמתחלפת בכל רינדור)
  const bookKey = book.text_path || book.pdf_path || book.image_path || book.name;
  useEffect(() => {
    setView(defaultView);
    setBookHits(null);
    setActiveHit(-1);
    setMeta(null);
    setToc(null);
    tocAutoClosedRef.current = false;
    setTocOpen(!compact || !!autoSearchQuery);
    posRef.current = { chunk: initChunk, absOffset: 0 };
    pdfPageRef.current = initPage;
    setPdfPage(initPage);

    if (book.text_path) {
      api
        .bookToc(book.text_path)
        .then((r) => setToc(r))
        .catch(() => setToc(null));
    }
  }, [bookKey]);

  const fontFamily = settings.font_family || "FrankRuehl";

  // ---- מיקום ----
  const onTextPosition = useCallback((chunk, absOffset) => {
    posRef.current = { chunk, absOffset };
  }, []);

  const closeTocOnScroll = useCallback(() => {
    // סגירה אוטומטית של עץ הכותרות אחרי שמתחילים לגלול (פעם אחת)
    if (!tocAutoClosedRef.current) {
      tocAutoClosedRef.current = true;
      setTimeout(() => setTocOpen(false), 400);
    }
  }, []);

  // ---- מעבר תצוגות (לפי כותרות) ----
  async function switchView(next) {
    if (next === view) return;
    if (next === "pdf" && book.pdf_path) {
      let page = 1;
      try {
        const r = await api.syncPosition({
          text_path: book.text_path,
          pdf_path: book.pdf_path,
          direction: "to_pdf",
          offset: posRef.current.absOffset || 0,
        });
        if (r.ok && r.page) page = r.page;
      } catch (e) {}
      pdfPageRef.current = page;
      setPdfPage(page);
      setView("pdf");
      return;
    }
    if (next === "text" && book.text_path) {
      let chunk = 0, offset = null;
      try {
        const r = await api.syncPosition({
          text_path: book.text_path,
          pdf_path: book.pdf_path,
          direction: "to_text",
          page: pdfPageRef.current || 1,
        });
        if (r.ok) {
          chunk = r.chunk || 0;
          offset = r.offset != null ? r.offset : null;
        }
      } catch (e) {}
      setTextTarget({ chunk, offset, seq: seqRef.current++ });
      setView("text");
      return;
    }
    setView(next);
  }

  // ---- עץ כותרות ----
  function gotoHeading(h) {
    if (view === "text") {
      setTextTarget({ chunk: h.chunk, offset: h.offset, seq: seqRef.current++ });
    } else if (view === "pdf" && book.pdf_path && book.text_path) {
      // קפיצה לכותרת בתוך ה-PDF דרך מנגנון הסנכרון
      api
        .syncPosition({
          text_path: book.text_path,
          pdf_path: book.pdf_path,
          direction: "to_pdf",
          offset: h.abs_offset,
        })
        .then((r) => {
          if (r.ok && r.page && pdfRef.current) pdfRef.current.scrollToPage(r.page);
        })
        .catch(() => {});
    }
  }

  // ---- חיפוש בספר ----
  const searchPath =
    view === "pdf" ? book.pdf_path : view === "image" ? book.image_path : book.text_path || book.pdf_path;

  function onSearchResults(res) {
    if (res.kind === "text") {
      setBookHits(res.hits);
    } else {
      setBookHits(null);
    }
    setActiveHit(-1);
  }

  function onGotoHit(idx, hit, res) {
    setActiveHit(idx);
    if (res.kind === "text") {
      textRef.current && textRef.current.gotoHit(idx, res.hits);
    } else if (hit.page && pdfRef.current) {
      pdfRef.current.scrollToPage(hit.page);
    }
  }

  // ---- סימניות ----
  async function saveBookmark() {
    const isPdf = view === "pdf";
    const position = JSON.stringify(
      isPdf
        ? { page: pdfPageRef.current }
        : { chunk: posRef.current.chunk, offset: null, abs: posRef.current.absOffset }
    );
    const label = isPdf
      ? `עמוד ${pdfPageRef.current}`
      : meta
      ? `קטע ${posRef.current.chunk + 1} מתוך ${meta.total_chunks}`
      : "";
    try {
      await api.addBookmark({
        book_path: isPdf ? book.pdf_path : book.text_path || book.image_path,
        book_name: book.name,
        view,
        position,
        label,
      });
      onToast && onToast("הסימנייה נשמרה", "ok");
    } catch (e) {
      onToast && onToast("שמירת סימנייה נכשלה: " + e.message, "error");
    }
  }

  const [exportOpen, setExportOpen] = useState(false);

  // ---- OCR מלא בכפייה (כששכבת הטקסט של הקובץ פגומה) ----
  async function forceOcr() {
    if (!window.confirm(
      "הפעולה תגרום לתוכנה להתעלם מהטקסט המוטמע בקובץ זה ולסרוק את כל " +
      "עמודיו מחדש ב-OCR (במנוע האינדוקס הנבחר).\n" +
      "מיועד לקבצים שהטקסט שלהם משובש (למשל הפוך). הסריקה תרוץ ברקע " +
      "ועשויה לקחת זמן. להמשיך?"
    )) return;
    try {
      await api.forceOcr(book.pdf_path);
      onToast && onToast("הקובץ נכנס לתור ה-OCR - ההתקדמות מוצגת בסרגל הצד", "ok");
    } catch (e) {
      onToast && onToast(e.message, "error");
    }
  }

  const showToc = view !== "image" && (toc || searchPath);

  return (
    <div className={"book-viewer" + (compact ? " compact" : "")}>
      <div className="viewer-toolbar">
        <div className="viewer-title" title={book.name}>{book.name}</div>

        {showToc && (
          <button
            className={"btn btn-sm" + (tocOpen ? " btn-primary" : "")}
            onClick={() => { setTocOpen((v) => !v); tocAutoClosedRef.current = true; }}
            title="עץ כותרות וחיפוש בספר"
          >
            ☰ עץ / חיפוש
          </button>
        )}

        {view === "text" && (
          <>
            <button className="btn btn-sm" onClick={() => setFontSize((s) => Math.min(60, s + 1))} title="הגדל טקסט">א+</button>
            <button className="btn btn-sm" onClick={() => setFontSize((s) => Math.max(10, s - 1))} title="הקטן טקסט">א−</button>
            {meta && meta.has_niqqud && (
              <button className={"btn btn-sm" + (removeNiqqud ? " btn-primary" : "")} onClick={() => setRemoveNiqqud((v) => !v)} title="הסר/החזר ניקוד">
                ניקוד
              </button>
            )}
            {meta && meta.has_teamim && (
              <button className={"btn btn-sm" + (removeTeamim ? " btn-primary" : "")} onClick={() => setRemoveTeamim((v) => !v)} title="הסר/החזר טעמי מקרא">
                טעמים
              </button>
            )}
          </>
        )}

        {isDual && (
          <button className="btn btn-sm" onClick={() => switchView(view === "pdf" ? "text" : "pdf")} title="מעבר בין תצוגת טקסט ל-PDF (לפי הכותרות)">
            {view === "pdf" ? "עבור לטקסט" : "עבור ל-PDF"}
          </button>
        )}

        {view === "pdf" && book.pdf_path && (
          <>
            <button className="btn btn-sm" onClick={() => setExportOpen(true)} title="ייצוא הטקסט של הקובץ (טקסט שמור / שכבת טקסט / OCR)">
              חלץ טקסט
            </button>
            <button className="btn btn-sm" onClick={forceOcr} title="הטקסט בקובץ משובש? התעלמות מהטקסט המוטמע וסריקת OCR מלאה ברקע">
              סרוק OCR מלא
            </button>
          </>
        )}

        {book.mefarshim && (
          <button className="btn btn-sm" onClick={() => onOpenMefarshim && onOpenMefarshim(book)} title="פתח מפרשים">
            מפרשים
          </button>
        )}

        <button className="btn btn-sm" onClick={saveBookmark} title="שמור סימנייה">🔖</button>
      </div>

      <div className="viewer-split">
        {showToc && tocOpen && (
          <TocPanel
            toc={view !== "pdf" || book.text_path ? toc : null}
            searchPath={searchPath}
            canSearch={!!searchPath}
            initialQuery={autoSearchQuery}
            onGotoHeading={gotoHeading}
            onSearchResults={onSearchResults}
            onGotoHit={onGotoHit}
            onClose={() => setTocOpen(false)}
            onToast={onToast}
          />
        )}

        <div className="viewer-body">
          {view === "text" && book.text_path && (
            <TextBookViewer
              ref={textRef}
              path={book.text_path}
              fontSize={fontSize}
              fontFamily={fontFamily}
              removeNiqqud={removeNiqqud}
              removeTeamim={removeTeamim}
              hits={bookHits}
              activeHit={activeHit}
              onPosition={onTextPosition}
              onUserScroll={closeTocOnScroll}
              onMeta={setMeta}
              target={textTarget}
            />
          )}

          {view === "pdf" && book.pdf_path && (
            <PdfViewer
              ref={pdfRef}
              key={book.pdf_path}
              path={book.pdf_path}
              initialPage={pdfPage}
              onPageChange={(p, t) => {
                pdfPageRef.current = p;
                if (t) setPdfTotal(t);
              }}
              onTotalPages={setPdfTotal}
              onUserScroll={closeTocOnScroll}
              onToast={onToast}
            />
          )}

          {view === "image" && book.image_path && (
            <ImageViewer path={book.image_path} onToast={onToast} />
          )}
        </div>
      </div>

      {exportOpen && book.pdf_path && (
        <ExportDialog
          book={book}
          currentPage={pdfPageRef.current || 1}
          totalPages={pdfTotal}
          onClose={() => setExportOpen(false)}
          onToast={onToast}
        />
      )}
    </div>
  );
}
