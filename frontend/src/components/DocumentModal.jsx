import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// מרנדר טקסט מלא עם הדגשות לפי טווחים מוחלטים, וממספר כל הדגשה לניווט.
function renderWithSpans(text, spans) {
  if (!spans || spans.length === 0) return [<span key="all">{text}</span>];
  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const nodes = [];
  let cursor = 0;
  let idx = 0;
  for (const [start, end] of sorted) {
    if (start < cursor) continue;
    if (start > cursor) nodes.push(<span key={"t" + cursor}>{text.slice(cursor, start)}</span>);
    nodes.push(
      <mark key={"m" + start} className="hl" data-hit={idx}>
        {text.slice(start, end)}
      </mark>
    );
    idx++;
    cursor = end;
  }
  if (cursor < text.length) nodes.push(<span key="tail">{text.slice(cursor)}</span>);
  return nodes;
}

export default function DocumentModal({ fileId, query, jump, searchOpts, onClose, onToast }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);
  const [current, setCurrent] = useState(0);
  const bodyRef = useRef(null);

  useEffect(() => {
    setDoc(null);
    setError(null);
    api
      .document(fileId, query, searchOpts || {})
      .then(setDoc)
      .catch((e) => setError(e.message));
  }, [fileId, query, searchOpts]);

  useEffect(() => {
    if (doc && doc.spans && doc.spans.length > 0) {
      // אם התבקשה קפיצה להופעה מסוימת - נאתר את ההופעה הקרובה להיסט
      let startIdx = 0;
      if (jump != null) {
        const sorted = [...doc.spans].sort((a, b) => a[0] - b[0]);
        const found = sorted.findIndex((s) => s[0] >= jump);
        startIdx = found >= 0 ? found : 0;
      }
      setCurrent(startIdx);
      setTimeout(() => scrollToHit(startIdx), 60);
    }
  }, [doc, jump]);

  function scrollToHit(i) {
    const el = bodyRef.current?.querySelector(`mark[data-hit="${i}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      bodyRef.current.querySelectorAll("mark.active").forEach((m) => m.classList.remove("active"));
      el.classList.add("active");
    }
  }

  const hits = doc?.spans?.length || 0;

  function nav(delta) {
    if (hits === 0) return;
    let next = (current + delta + hits) % hits;
    setCurrent(next);
    scrollToHit(next);
  }

  async function openInApp() {
    try {
      await api.open(doc.path, null);
    } catch (e) {
      onToast && onToast("פתיחה נכשלה: " + e.message, "error");
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="doc-name">{doc?.name || "טוען..."}</span>
            {doc && <span className="doc-path">{doc.path}</span>}
          </div>
          <div className="modal-actions">
            {hits > 0 && (
              <div className="nav-hits">
                <button onClick={() => nav(-1)} title="הקודם">‹</button>
                <span>
                  {current + 1} / {hits}
                </span>
                <button onClick={() => nav(1)} title="הבא">›</button>
              </div>
            )}
            <button className="btn" onClick={openInApp}>פתח בתוכנה</button>
            <a className="btn" href={api.exportDocumentUrl(fileId)}>ייצא טקסט</a>
            <button className="btn btn-close" onClick={onClose}>סגור</button>
          </div>
        </div>
        <div className="modal-body" ref={bodyRef}>
          {error && <div className="error-box">שגיאה: {error}</div>}
          {!doc && !error && <div className="loading">טוען מסמך…</div>}
          {doc && <pre className="doc-text">{renderWithSpans(doc.full_text, doc.spans)}</pre>}
        </div>
      </div>
    </div>
  );
}
