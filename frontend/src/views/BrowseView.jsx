import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import TreeView from "../components/TreeView.jsx";
import BookViewer from "../components/BookViewer.jsx";

// חלונית "עיון": עץ ספרים (ימין) + מציג (מרכז) + מפרשים (שמאל).
export default function BrowseView({ settings, onToast }) {
  const [tree, setTree] = useState([]);
  const [book, setBook] = useState(null);
  const [initial, setInitial] = useState({ view: null, position: null });
  const [mefBook, setMefBook] = useState(null); // הספר שמפרשיו פתוחים
  const [mefList, setMefList] = useState([]);
  const [mefSelected, setMefSelected] = useState(null);

  useEffect(() => {
    api.tree().then((r) => setTree(r.tree)).catch(() => {});
  }, []);

  function openBook(node) {
    setBook(node);
    setInitial({ view: null, position: null });
    setMefBook(null);
    setMefSelected(null);
  }

  async function openMefarshim(b) {
    try {
      const r = await api.mefarshim(b.mefarshim);
      setMefList(r.books);
      setMefBook(b);
      setMefSelected(r.books[0] || null);
      if (r.books.length === 0) onToast("לא נמצאו מפרשים בתיקייה", "error");
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  return (
    <div className="browse-view">
      <div className="browse-tree">
        <TreeView tree={tree} openBook={openBook} />
      </div>

      <div className="browse-main">
        {!book && (
          <div className="empty">
            <div className="empty-icon">📚</div>
            <p>בחרו ספר מהעץ (לחיצה כפולה) כדי לפתוח אותו כאן</p>
          </div>
        )}
        {book && (
          <BookViewer
            key={(book.text_path || book.pdf_path || book.image_path || book.name) + (initial.position || "")}
            book={book}
            settings={settings}
            initialView={initial.view}
            initialPosition={initial.position}
            onToast={onToast}
            onOpenMefarshim={openMefarshim}
          />
        )}
      </div>

      {mefBook && (
        <div className="mefarshim-panel">
          <div className="mef-head">
            <b>מפרשים — {mefBook.name}</b>
            <button className="btn btn-sm" onClick={() => setMefBook(null)}>סגור</button>
          </div>
          <select
            value={mefSelected ? mefSelected.path : ""}
            onChange={(e) => setMefSelected(mefList.find((m) => m.path === e.target.value) || null)}
          >
            {mefList.map((m) => (
              <option key={m.path} value={m.path}>{m.name}</option>
            ))}
          </select>
          {mefSelected && (
            <BookViewer
              key={mefSelected.path}
              book={{
                kind: "book",
                name: mefSelected.name,
                dual: false,
                text_path: mefSelected.type === "text" ? mefSelected.path : null,
                pdf_path: mefSelected.type === "pdf" ? mefSelected.path : null,
                image_path: mefSelected.type === "image" ? mefSelected.path : null,
              }}
              settings={settings}
              onToast={onToast}
              compact
            />
          )}
        </div>
      )}
    </div>
  );
}
