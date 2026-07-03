import React, { useState } from "react";
import { api, copyText, downloadText, pickSaveFile } from "../api.js";

// חלונית תוצאת OCR משותפת (מציג תמונות ומציג PDF): הצגת הטקסט שחולץ
// עם העתקה ללוח ושמירה כ-TXT/WORD דרך דיאלוג "שמירה בשם" נייטיבי.
export default function OcrResultPanel({ text, baseName, onClose, onToast }) {
  const [saveMenu, setSaveMenu] = useState(false);

  async function saveAs(format) {
    setSaveMenu(false);
    const defaultName = (baseName || "ocr") + (format === "docx" ? ".docx" : ".txt");
    try {
      // דיאלוג "שמירה בשם" נייטיב (בגרסת השולחן); בנפילה - הורדה רגילה
      const target = await pickSaveFile(defaultName, format);
      if (target) {
        await api.saveTextFile(target, text, format);
        onToast && onToast("הקובץ נשמר: " + target, "ok");
      } else if (format === "txt") {
        downloadText(text, defaultName);
      } else {
        onToast && onToast("לא נבחר מיקום שמירה", "error");
      }
    } catch (e) {
      onToast && onToast("השמירה נכשלה: " + e.message, "error");
    }
  }

  return (
    <div className="ocr-result">
      <div className="ocr-result-head">
        <b>טקסט מחולץ</b>
        <div className="ocr-actions">
          <button
            className="btn btn-sm"
            onClick={async () => {
              const ok = await copyText(text);
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
          <button className="btn btn-sm" onClick={onClose}>סגור</button>
          {saveMenu && (
            <div className="save-menu">
              <button className="btn btn-sm" onClick={() => saveAs("txt")}>שמור כקובץ TXT</button>
              <button className="btn btn-sm" onClick={() => saveAs("docx")}>שמור כקובץ WORD</button>
            </div>
          )}
        </div>
      </div>
      <pre className="doc-text ocr-text">{text}</pre>
    </div>
  );
}
