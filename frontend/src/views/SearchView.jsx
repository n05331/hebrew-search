import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import ScopeTree from "../components/ScopeTree.jsx";
import Highlight from "../components/Highlight.jsx";
import BookViewer from "../components/BookViewer.jsx";

const PAGE_SIZE = 20;

const EXT_ICONS = { ".pdf": "📕", ".docx": "📘", ".txt": "📄", ".md": "📝" };

function bookFromResult(r) {
  const ext = (r.ext || "").toLowerCase();
  const isPdf = ext === ".pdf";
  const isImage = [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"].includes(ext);
  return {
    kind: isImage ? "image" : "book",
    name: r.name.replace(/\.[^.]+$/, ""),
    dual: false,
    text_path: !isPdf && !isImage ? r.path : null,
    pdf_path: isPdf ? r.path : null,
    image_path: isImage ? r.path : null,
  };
}

export default function SearchView({ settings, progress, onToast }) {
  const [tree, setTree] = useState([]);
  const [scope, setScope] = useState(() => new Set());

  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [opts, setOpts] = useState({ exact: false, whole_word: false, fold_vy: false, fold_aa: false, min_words: 0 });

  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [searchTime, setSearchTime] = useState(null);
  const [expandedDups, setExpandedDups] = useState(() => new Set());
  const [liveProgress, setLiveProgress] = useState(null);

  const [openBook, setOpenBook] = useState(null); // {book, page, query}

  const sentinelRef = useRef(null);
  const loadingRef = useRef(false);
  const progressTimerRef = useRef(null);

  useEffect(() => {
    api.tree().then((r) => setTree(r.tree)).catch(() => {});
  }, []);

  const resultLimit = parseInt(settings.result_limit || "0", 10);
  const proximity = parseInt(settings.proximity_words || "30", 10);
  const resultFontSize = parseInt(settings.result_font_size || "25", 10);
  const fontFamily = settings.font_family || "FrankRuehl";

  const buildBody = useCallback(
    (q, offset) => ({
      q,
      limit: PAGE_SIZE,
      offset,
      exact: opts.exact,
      whole_word: opts.whole_word,
      fold_vy: opts.fold_vy,
      fold_aa: opts.fold_aa,
      min_words: opts.min_words,
      proximity,
      paths: [...scope],
    }),
    [opts, scope, proximity]
  );

  // חיווי התקדמות חי בזמן חיפוש
  function startProgressPolling() {
    stopProgressPolling();
    progressTimerRef.current = setInterval(async () => {
      try {
        const p = await api.searchProgress();
        setLiveProgress(p.running ? p : null);
      } catch (e) {}
    }, 300);
  }
  function stopProgressPolling() {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    setLiveProgress(null);
  }
  useEffect(() => () => stopProgressPolling(), []);

  const newSearch = useCallback(
    async (q) => {
      if (!q.trim()) { setResults([]); setTotal(0); setActiveQuery(""); return; }
      loadingRef.current = true;
      setLoading(true);
      setSearchError(null);
      setOpenBook(null);
      startProgressPolling();
      const t0 = performance.now();
      try {
        const data = await api.searchPost(buildBody(q, 0));
        setResults(data.results);
        setTotal(data.total);
        setActiveQuery(q);
        setSearchTime(Math.round(performance.now() - t0));
      } catch (e) {
        setSearchError(e.message);
        setResults([]);
        setTotal(0);
      } finally {
        setLoading(false);
        loadingRef.current = false;
        stopProgressPolling();
      }
    },
    [buildBody]
  );

  const effectiveMax = resultLimit > 0 ? Math.min(total, resultLimit) : total;

  const loadMore = useCallback(async () => {
    if (loadingRef.current || !activeQuery) return;
    if (results.length >= effectiveMax) return;
    loadingRef.current = true;
    setLoadingMore(true);
    try {
      const data = await api.searchPost(buildBody(activeQuery, results.length));
      setResults((prev) => {
        const seen = new Set(prev.map((r) => r.file_id));
        const merged = [...prev, ...data.results.filter((r) => !seen.has(r.file_id))];
        return resultLimit > 0 ? merged.slice(0, resultLimit) : merged;
      });
      setTotal(data.total);
    } catch (e) {
    } finally {
      setLoadingMore(false);
      loadingRef.current = false;
    }
  }, [activeQuery, results.length, effectiveMax, buildBody, resultLimit]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) loadMore(); },
      { rootMargin: "300px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  function openResult(r, page) {
    setOpenBook({
      book: bookFromResult(r),
      page: page || (r.matches[0] && r.matches[0].page) || 1,
      query: activeQuery,
    });
  }

  function openDuplicate(d, page) {
    setOpenBook({ book: bookFromResult(d), page: page || 1, query: activeQuery });
  }

  function toggleOpt(key) {
    setOpts((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  const hasMore = results.length < effectiveMax;
  const ocr = progress && progress.ocr;
  const bookOpen = !!openBook;

  // הערכת זמן נותר לפי קצב הבדיקה
  let progressText = null;
  if (liveProgress && liveProgress.running && liveProgress.candidates > 0) {
    const { checked, candidates, elapsed } = liveProgress;
    let eta = "";
    if (elapsed > 0.3 && checked > 3) {
      const rate = checked / elapsed;
      const remain = Math.max(0, Math.ceil((candidates - checked) / Math.max(1, rate)));
      eta = ` · נותרו כ-${remain} שניות`;
    }
    progressText = `נבדקו ${checked} מתוך ${candidates} קבצים${eta}`;
  }

  const resultsList = (
    <div className="results">
      {results.map((r) => (
        <div className="result-card" key={r.file_id}>
          <div className="result-head">
            <span className="result-icon">{EXT_ICONS[r.ext] || "📄"}</span>
            <button className="result-name" onClick={() => openResult(r)} title="פתח את הספר במיקום">
              {r.name}
            </button>
            <span className="badge">{r.occurrences} התאמות</span>
            {r.duplicates && r.duplicates.length > 0 && (
              <button
                className="badge badge-dup"
                onClick={() =>
                  setExpandedDups((prev) => {
                    const next = new Set(prev);
                    next.has(r.file_id) ? next.delete(r.file_id) : next.add(r.file_id);
                    return next;
                  })
                }
                title="אותה תוצאה נמצאה גם בספרים נוספים"
              >
                נמצא ב-{r.duplicates.length + 1} ספרים {expandedDups.has(r.file_id) ? "▴" : "▾"}
              </button>
            )}
            {(r.source === "ocr" || r.source === "mixed") && <span className="badge badge-ocr">OCR</span>}
          </div>

          {expandedDups.has(r.file_id) && r.duplicates && (
            <div className="dup-list">
              {r.duplicates.map((d) => (
                <button key={d.file_id} className="link-btn" onClick={() => openDuplicate(d)}>
                  {d.name}
                </button>
              ))}
            </div>
          )}

          <div className="result-meta">
            <span className="result-path" title={r.path}>{r.path}</span>
          </div>

          <div className="snippets" style={{ fontSize: resultFontSize + "px", fontFamily }}>
            {r.matches.map((m, i) => (
              <div key={i} className="snippet" onClick={() => openResult(r, m.page)} title="פתח את הספר במיקום זה">
                <div className="snippet-text">
                  <Highlight text={m.snippet} spans={m.spans} />
                </div>
                {m.page ? <span className="snippet-page">עמ׳ {m.page}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ))}

      {!loading && activeQuery && results.length === 0 && !searchError && (
        <div className="empty">
          <div className="empty-icon">🗂️</div>
          <p>לא נמצאו תוצאות. נסו ניסוח אחר, או הפעילו "כתיב מלא/חסר".</p>
        </div>
      )}

      <div ref={sentinelRef} className="scroll-sentinel" />
      {loadingMore && <div className="loading-more">טוען עוד…</div>}
      {!hasMore && results.length > 0 && !loading && (
        <div className="end-of-results">— סוף התוצאות —</div>
      )}
    </div>
  );

  return (
    <div className={"search2-view" + (bookOpen ? " with-book" : "")}>
      {/* עץ היקף - ימין (מוסתר כשספר פתוח) */}
      {!bookOpen && (
        <div className="search2-scope">
          <form
            className="scope-searchbar"
            onSubmit={(e) => { e.preventDefault(); newSearch(query); }}
          >
            <input
              className="search-input"
              type="text"
              placeholder="חפשו בספרים…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
            <button className="btn btn-primary" type="submit">חפש</button>
          </form>

          <div className="search-opts">
            <label className="chk" title="ימצא גם עם/בלי אותיות ו/י (חלום=חלם)">
              <input type="checkbox" checked={opts.fold_vy} onChange={() => toggleOpt("fold_vy")} />
              כתיב מלא/חסר
            </label>
            <label className="chk" title="ימצא גם עם/בלי אותיות ע/א">
              <input type="checkbox" checked={opts.fold_aa} onChange={() => toggleOpt("fold_aa")} />
              אידיש
            </label>
            <label className="chk" title="רק בסדר ובצורה המדויקת שנכתב">
              <input type="checkbox" checked={opts.exact} onChange={() => toggleOpt("exact")} />
              חיפוש מדויק
            </label>
            <label className="chk" title="ללא הרחבת תחיליות וסיומות">
              <input type="checkbox" checked={opts.whole_word} onChange={() => toggleOpt("whole_word")} />
              מילה שלימה
            </label>
            <label className="chk min-words" title="כמה מילים מהחיפוש חייבות להופיע">
              לפחות
              <select
                value={opts.min_words}
                onChange={(e) => setOpts((p) => ({ ...p, min_words: parseInt(e.target.value, 10) }))}
              >
                <option value="0">כל המילים</option>
                {[1,2,3,4,5,6,7,8,9,10].map((n) => (
                  <option key={n} value={n}>{n} מילים</option>
                ))}
              </select>
            </label>
          </div>

          <ScopeTree tree={tree} selected={scope} setSelected={setScope} />
        </div>
      )}

      {/* תוצאות: מרכז (רגיל) או ימין רבע-מסך (כשספר פתוח) */}
      <div className={bookOpen ? "search2-results-side" : "search2-results"}>
        {ocr && (ocr.running || ocr.pending > 0) && !bookOpen && (
          <div className="ocr-note">
            עוד {ocr.pending} קבצים בעיבוד OCR ברקע — התוצאות יתעדכנו בהדרגה
          </div>
        )}

        <div className="results-toolbar">
          <div className="results-summary">
            {loading ? "מחפש…" : activeQuery ? (
              <>
                נמצאו <b>{total}</b> תוצאות עבור «{activeQuery}»
                {resultLimit > 0 && total > resultLimit && <span className="muted"> (מוצגות {resultLimit})</span>}
                {searchTime != null && <span className="muted"> ({searchTime} מ״ש)</span>}
              </>
            ) : (
              "הקלידו שאילתה כדי להתחיל"
            )}
          </div>
          {bookOpen && (
            <button className="btn btn-sm" onClick={() => setOpenBook(null)}>סגור ספר</button>
          )}
        </div>

        {loading && (
          <div className="search-progress">
            <div className="search-progress-anim" />
            <div className="search-progress-text">
              {progressText || "מחפש…"}
            </div>
            {liveProgress && liveProgress.candidates > 0 && (
              <div className="search-progress-bar">
                <div
                  className="search-progress-fill"
                  style={{ width: Math.round((liveProgress.checked / liveProgress.candidates) * 100) + "%" }}
                />
              </div>
            )}
          </div>
        )}

        {searchError && <div className="error-box">שגיאת חיפוש: {searchError}</div>}

        {resultsList}
      </div>

      {/* ספר פתוח - במרכז, עם כל הגדרות התצוגה של חלונית עיון */}
      {bookOpen && (
        <div className="search2-book-main">
          <BookViewer
            key={(openBook.book.text_path || openBook.book.pdf_path || openBook.book.image_path) + activeQuery}
            book={openBook.book}
            settings={settings}
            initialPosition={JSON.stringify({ page: openBook.page })}
            autoSearchQuery={openBook.query}
            onToast={onToast}
          />
        </div>
      )}
    </div>
  );
}
