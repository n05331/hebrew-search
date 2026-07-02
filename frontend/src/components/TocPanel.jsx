import React, { useState } from "react";
import { api } from "../api.js";
import Highlight from "./Highlight.jsx";

// חלונית צד לספר פתוח: שתי לשוניות - 1. עץ כותרות  2. חיפוש בספר.
// נפתחת אוטומטית עם הספר, נסגרת אוטומטית בגלילה (בשליטת ההורה).
//
// props:
//   toc          {headings:[{level,title,chunk,offset,abs_offset}]} או null (אין כותרות / PDF)
//   searchPath   הנתיב שבו יבוצע חיפוש-בספר (לפי התצוגה הפעילה)
//   canSearch    האם חיפוש זמין
//   onGotoHeading(h)
//   onSearchResults(res)   תוצאות חיפוש-בספר (להדגשות אצל ההורה)
//   onGotoHit(idx, hit, res)
//   onClose()
//   onToast

export default function TocPanel({
  toc,
  searchPath,
  canSearch = true,
  initialQuery,
  onGotoHeading,
  onSearchResults,
  onGotoHit,
  onClose,
  onToast,
}) {
  const hasToc = toc && toc.headings && toc.headings.length > 0;
  const [tab, setTab] = useState(initialQuery ? "search" : hasToc ? "toc" : "search");
  const [query, setQuery] = useState(initialQuery || "");
  const [opts, setOpts] = useState({ exact: false, whole_word: false, fold_vy: false, fold_aa: false });
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const autoRanRef = React.useRef(false);

  // חיפוש אוטומטי כשנפתח מתוצאת חיפוש ראשית
  React.useEffect(() => {
    if (initialQuery && searchPath && !autoRanRef.current) {
      autoRanRef.current = true;
      setTab("search");
      runSearchFor(initialQuery);
    }
  }, [initialQuery, searchPath]);

  // אם ה-TOC הגיע באיחור והמשתמש בלשונית חיפוש ריקה - נעבור לכותרות
  React.useEffect(() => {
    if (hasToc && tab === "search" && !results && !query) setTab("toc");
  }, [hasToc]);

  const firstMountRef = React.useRef(true);
  React.useEffect(() => {
    // החלפת יעד חיפוש (מעבר תצוגה/ספר) - איפוס תוצאות; לא ברינדור הראשון
    if (firstMountRef.current) {
      firstMountRef.current = false;
      return;
    }
    setResults(null);
    setActiveIdx(-1);
  }, [searchPath]);

  async function runSearchFor(q) {
    if (!q.trim() || !searchPath) return;
    setBusy(true);
    try {
      const res = await api.bookSearch({ path: searchPath, q: q.trim(), ...opts });
      setResults(res);
      setActiveIdx(-1);
      onSearchResults && onSearchResults(res);
      if (res.total === 0) {
        onToast && onToast(res.message || "לא נמצאו הופעות בספר", "error");
      } else {
        setActiveIdx(0);
        onGotoHit && onGotoHit(0, res.hits[0], res);
      }
    } catch (e2) {
      onToast && onToast(e2.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function runSearch(e) {
    e && e.preventDefault();
    runSearchFor(query);
  }

  function toggleOpt(key) {
    setOpts((p) => ({ ...p, [key]: !p[key] }));
  }

  function gotoHit(idx) {
    if (!results || !results.hits.length) return;
    const clamped = ((idx % results.hits.length) + results.hits.length) % results.hits.length;
    setActiveIdx(clamped);
    onGotoHit && onGotoHit(clamped, results.hits[clamped], results);
  }

  return (
    <div className="toc-panel">
      <div className="toc-tabs">
        {hasToc && (
          <button
            className={"toc-tab" + (tab === "toc" ? " active" : "")}
            onClick={() => setTab("toc")}
          >
            עץ כותרות
          </button>
        )}
        {canSearch && (
          <button
            className={"toc-tab" + (tab === "search" ? " active" : "")}
            onClick={() => setTab("search")}
          >
            חיפוש בספר
          </button>
        )}
        <button className="icon-btn toc-close" onClick={onClose} title="סגור חלונית">✕</button>
      </div>

      {tab === "toc" && hasToc && (
        <div className="toc-body">
          {toc.headings.map((h, i) => (
            <div
              key={i}
              className={"toc-item toc-l" + h.level}
              onClick={() => onGotoHeading && onGotoHeading(h)}
              title={h.title}
            >
              {h.title}
            </div>
          ))}
        </div>
      )}

      {tab === "search" && (
        <div className="toc-search">
          <form onSubmit={runSearch} className="toc-search-form">
            <input
              type="text"
              placeholder="חיפוש בתוך הספר…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="btn btn-sm btn-primary" type="submit" disabled={busy}>
              {busy ? "…" : "חפש"}
            </button>
          </form>
          <div className="toc-search-opts">
            <label className="chk" title="ימצא גם עם/בלי אותיות ו/י">
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
          </div>

          {results && results.total > 0 && (
            <div className="toc-hit-nav">
              <button className="btn btn-sm" onClick={() => gotoHit(activeIdx - 1)}>‹</button>
              <span>{activeIdx + 1} / {results.total}</span>
              <button className="btn btn-sm" onClick={() => gotoHit(activeIdx + 1)}>›</button>
            </div>
          )}

          {results && results.pending && (
            <div className="muted toc-pending">{results.message}</div>
          )}

          <div className="toc-hits">
            {results &&
              results.hits.map((h, i) => (
                <div
                  key={i}
                  className={"toc-hit" + (i === activeIdx ? " active" : "")}
                  onClick={() => gotoHit(i)}
                >
                  <div className="toc-hit-snippet">
                    <Highlight text={h.snippet} spans={h.hl ? [h.hl] : []} />
                  </div>
                  {h.page != null && <span className="snippet-page">עמ׳ {h.page}</span>}
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
