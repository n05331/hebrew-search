import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import BookViewer from "../components/BookViewer.jsx";

// חלונית "סימניות": רשימה (ימין, רבע מסך כשספר פתוח), פתיחת הסימנייה
// באותה חלונית במרכז עם כל הגדרות התצוגה של חלונית עיון.
export default function BookmarksView({ settings, onToast, active = true }) {
  const [items, setItems] = useState([]);
  const [term, setTerm] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [openBm, setOpenBm] = useState(null); // הסימנייה הפתוחה

  function openBookmark(b) {
    const isPdf = b.view === "pdf";
    const ext = (b.book_path || "").toLowerCase();
    const isImage = [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"].some((e) =>
      ext.endsWith(e)
    );
    const book = {
      kind: isImage ? "image" : "book",
      name: b.book_name,
      dual: false,
      text_path: !isPdf && !isImage ? b.book_path : null,
      pdf_path: isPdf ? b.book_path : null,
      image_path: isImage ? b.book_path : null,
    };
    setOpenBm({ book, view: b.view, position: b.position, id: b.id });
  }

  async function refresh() {
    try {
      const r = await api.bookmarks();
      setItems(r.bookmarks);
      setSelected(new Set());
    } catch (e) {}
  }

  // רענון בכל כניסה ללשונית (הרכיב נשאר טעון ברקע)
  useEffect(() => {
    if (active) refresh();
  }, [active]);

  async function remove(id) {
    await api.deleteBookmark(id);
    refresh();
  }

  async function removeSelected() {
    if (selected.size === 0) return;
    try {
      await api.deleteBookmarks([...selected]);
      onToast(`נמחקו ${selected.size} סימניות`, "ok");
      refresh();
    } catch (e) {
      onToast(e.message, "error");
    }
  }

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const filtered = items.filter(
    (b) => !term || b.book_name.includes(term) || (b.label || "").includes(term)
  );
  const allChecked = filtered.length > 0 && filtered.every((b) => selected.has(b.id));

  const listPane = (
    <>
      <div className="view-header">
        <h2>סימניות</h2>
        <input
          type="text"
          placeholder="סינון סימניות…"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        {filtered.length > 0 && (
          <label className="chk">
            <input
              type="checkbox"
              checked={allChecked}
              onChange={(e) =>
                setSelected(e.target.checked ? new Set(filtered.map((b) => b.id)) : new Set())
              }
            />
            בחר הכל
          </label>
        )}
        {selected.size > 0 && (
          <button className="btn btn-danger btn-sm" onClick={removeSelected}>
            מחק {selected.size} נבחרות
          </button>
        )}
      </div>

      {filtered.length === 0 && (
        <div className="empty">
          <div className="empty-icon">🔖</div>
          <p>אין סימניות עדיין. שמרו סימנייה מתוך ספר פתוח בחלונית עיון.</p>
        </div>
      )}

      <div className="bookmark-list">
        {filtered.map((b) => (
          <div
            className={"bookmark-row" + (openBm && openBm.id === b.id ? " active" : "")}
            key={b.id}
          >
            <input
              type="checkbox"
              checked={selected.has(b.id)}
              onChange={() => toggle(b.id)}
              title="בחר למחיקה מרובה"
            />
            <div className="bookmark-info" onClick={() => openBookmark(b)} title="פתח במקום השמור">
              <b>{b.book_name}</b>
              <span className="muted">{b.label}</span>
              <span className="muted bookmark-date">
                {new Date(b.created_at * 1000).toLocaleString("he-IL")}
              </span>
            </div>
            <button className="icon-btn" onClick={() => remove(b.id)} title="מחק">✕</button>
          </div>
        ))}
      </div>
    </>
  );

  if (!openBm) {
    return <div className="bookmarks-view">{listPane}</div>;
  }

  // סימנייה פתוחה: רשימה ימין רבע-מסך, הספר במרכז עם כל כלי התצוגה
  return (
    <div className="bookmarks-split">
      <div className="bookmarks-side">
        <button className="btn btn-sm bm-close" onClick={() => setOpenBm(null)}>
          סגור ספר
        </button>
        {listPane}
      </div>
      <div className="bookmarks-book">
        <BookViewer
          key={openBm.id + (openBm.book.text_path || openBm.book.pdf_path || openBm.book.image_path || "")}
          book={openBm.book}
          settings={settings || {}}
          initialView={openBm.view}
          initialPosition={openBm.position}
          onToast={onToast}
        />
      </div>
    </div>
  );
}
