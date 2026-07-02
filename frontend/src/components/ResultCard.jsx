import React from "react";
import Highlight from "./Highlight.jsx";
import { api } from "../api.js";

const EXT_ICONS = {
  ".pdf": "📕",
  ".docx": "📘",
  ".txt": "📄",
  ".md": "📝",
  ".csv": "📊",
  ".png": "🖼️",
  ".jpg": "🖼️",
  ".jpeg": "🖼️",
  ".tif": "🖼️",
  ".tiff": "🖼️",
};

function fmtSize(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function fmtDate(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString("he-IL");
}

export default function ResultCard({ result, selected, onToggleSelect, onOpenDoc, onToast }) {
  const icon = EXT_ICONS[result.ext] || "📄";

  async function openLocation(page) {
    try {
      await api.open(result.path, page);
    } catch (e) {
      onToast && onToast("פתיחה נכשלה: " + e.message, "error");
    }
  }

  async function reveal() {
    try {
      await api.reveal(result.path);
    } catch (e) {
      onToast && onToast("פעולה נכשלה: " + e.message, "error");
    }
  }

  return (
    <div className={"result-card" + (selected ? " selected" : "")}>
      <div className="result-head">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          title="בחר לייצוא"
        />
        <span className="result-icon">{icon}</span>
        <button className="result-name" onClick={() => onOpenDoc(result.file_id)} title="פתח תצוגת מסמך">
          {result.name}
        </button>
        <span className="badge">{result.occurrences} התאמות</span>
        {result.source === "ocr" && <span className="badge badge-ocr">OCR</span>}
        {result.source === "mixed" && <span className="badge badge-ocr">OCR חלקי</span>}
      </div>

      <div className="result-meta">
        <span className="result-path" title={result.path}>{result.path}</span>
        <span className="dot">•</span>
        <span>{fmtSize(result.size)}</span>
        <span className="dot">•</span>
        <span>{fmtDate(result.mtime)}</span>
        {result.page_count > 1 && (
          <>
            <span className="dot">•</span>
            <span>{result.page_count} עמ׳</span>
          </>
        )}
      </div>

      <div className="snippets">
        {result.matches.map((m, i) => (
          <div key={i} className="snippet">
            <div className="snippet-text">
              <Highlight text={m.snippet} spans={m.spans} />
            </div>
            <div className="snippet-actions">
              {m.page ? <span className="snippet-page">עמ׳ {m.page}</span> : null}
              <button
                className="link-btn"
                onClick={() => openLocation(m.page)}
                title="פתח את הקובץ במיקום זה"
              >
                {m.page ? `פתח בעמוד ${m.page}` : "פתח קובץ"}
              </button>
              <button
                className="link-btn"
                onClick={() => onOpenDoc(result.file_id, m.abs_offset)}
                title="הצג הופעה זו בתצוגת המסמך"
              >
                הצג במסמך
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="result-actions">
        <button className="btn btn-sm" onClick={() => openLocation(result.matches[0]?.page)}>
          פתח במיקום
        </button>
        <button className="btn btn-sm" onClick={reveal}>הצג בתיקייה</button>
        <button className="btn btn-sm" onClick={() => onOpenDoc(result.file_id)}>תצוגת מסמך</button>
        <a className="btn btn-sm" href={api.exportDocumentUrl(result.file_id)}>ייצא טקסט</a>
      </div>
    </div>
  );
}
