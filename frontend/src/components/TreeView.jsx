import React, { useMemo, useState } from "react";

// עץ ספרים: תיקיות מקוננות, חיפוש בשמות, סגירת הכל, סינון סוג.

function nodeMatchesType(node, typeFilter) {
  if (typeFilter === "all") return true;
  if (node.kind === "image") return typeFilter === "image";
  if (node.dual) return true; // ספר כפול מכיל את שניהם
  if (typeFilter === "pdf") return !!node.pdf_path;
  if (typeFilter === "text") return !!node.text_path;
  return true;
}

function filterTree(nodes, term, typeFilter) {
  const out = [];
  for (const n of nodes) {
    if (n.kind === "folder") {
      const kids = filterTree(n.children || [], term, typeFilter);
      if (kids.length > 0 || (term && n.name.includes(term) && kids.length > 0)) {
        out.push({ ...n, children: kids });
      } else if (!term && kids.length > 0) {
        out.push({ ...n, children: kids });
      }
    } else {
      const nameOk = !term || n.name.includes(term);
      if (nameOk && nodeMatchesType(n, typeFilter)) out.push(n);
    }
  }
  return out;
}

function Folder({ node, depth, openBook, expandedSet, toggle }) {
  const isOpen = expandedSet.has(node.path);
  return (
    <div>
      <div
        className="tree-row tree-folder"
        style={{ paddingInlineStart: depth * 14 + 6 }}
        onClick={() => toggle(node.path)}
      >
        <span className="tree-arrow">{isOpen ? "▾" : "◂"}</span>
        <span className="tree-icon">📁</span>
        <span className="tree-name">{node.name}</span>
      </div>
      {isOpen &&
        (node.children || []).map((c, i) =>
          c.kind === "folder" ? (
            <Folder
              key={c.path || i}
              node={c}
              depth={depth + 1}
              openBook={openBook}
              expandedSet={expandedSet}
              toggle={toggle}
            />
          ) : (
            <BookRow key={(c.text_path || c.pdf_path || c.image_path || "") + i} node={c} depth={depth + 1} openBook={openBook} />
          )
        )}
    </div>
  );
}

function BookRow({ node, depth, openBook }) {
  const icon = node.kind === "image" ? "🖼️" : node.dual ? "📖" : node.pdf_path && !node.text_path ? "📕" : "📄";
  return (
    <div
      className="tree-row tree-book"
      style={{ paddingInlineStart: depth * 14 + 6 }}
      onDoubleClick={() => openBook(node)}
      title="לחיצה כפולה לפתיחה"
    >
      <span className="tree-icon">{icon}</span>
      <span className="tree-name">{node.name}</span>
      {node.dual && <span className="tree-tag">טקסט+PDF</span>}
      {node.mefarshim && <span className="tree-tag tag-mef">מפרשים</span>}
    </div>
  );
}

export default function TreeView({ tree, openBook }) {
  const [term, setTerm] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [expanded, setExpanded] = useState(() => new Set());

  const filtered = useMemo(
    () => filterTree(tree, term.trim(), typeFilter),
    [tree, term, typeFilter]
  );

  // בזמן חיפוש - פותחים את כל התיקיות שנשארו
  const allPaths = useMemo(() => {
    const acc = new Set();
    const walk = (nodes) =>
      nodes.forEach((n) => {
        if (n.kind === "folder") {
          acc.add(n.path);
          walk(n.children || []);
        }
      });
    walk(filtered);
    return acc;
  }, [filtered]);

  const effectiveExpanded = term.trim() ? allPaths : expanded;

  function toggle(path) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  }

  return (
    <div className="tree-panel">
      <div className="tree-toolbar">
        <input
          type="text"
          placeholder="חיפוש בשמות הספרים…"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        <div className="tree-controls">
          <button className="btn btn-sm" onClick={() => setExpanded(new Set())} title="סגור את כל העץ">
            סגור הכל
          </button>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="all">הכל</option>
            <option value="pdf">PDF</option>
            <option value="text">טקסט</option>
            <option value="image">תמונות</option>
          </select>
        </div>
      </div>
      <div className="tree-body">
        {filtered.length === 0 && <div className="muted tree-empty">אין ספרים להצגה</div>}
        {filtered.map((n, i) =>
          n.kind === "folder" ? (
            <Folder
              key={n.path || i}
              node={n}
              depth={0}
              openBook={openBook}
              expandedSet={effectiveExpanded}
              toggle={toggle}
            />
          ) : (
            <BookRow key={i} node={n} depth={0} openBook={openBook} />
          )
        )}
      </div>
    </div>
  );
}
