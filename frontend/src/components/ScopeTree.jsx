import React, { useMemo, useState } from "react";

// עץ ספרים עם תיבות סימון - לבחירת היקף החיפוש.
// selected = Set של נתיבים (קבצים). תיקייה מסומנת = כל הספרים שתחתיה.

export function collectBookPaths(node, acc) {
  if (node.kind === "folder") {
    (node.children || []).forEach((c) => collectBookPaths(c, acc));
  } else {
    if (node.text_path) acc.push(node.text_path);
    if (node.pdf_path) acc.push(node.pdf_path);
    if (node.image_path) acc.push(node.image_path);
  }
  return acc;
}

function nodePaths(node) {
  return collectBookPaths(node, []);
}

function FolderNode({ node, depth, selected, toggisSelected, togglePaths, expanded, toggleExpand, term }) {
  const paths = useMemo(() => nodePaths(node), [node]);
  const allSelected = paths.length > 0 && paths.every((p) => selected.has(p));
  const someSelected = !allSelected && paths.some((p) => selected.has(p));
  const isOpen = term ? true : expanded.has(node.path);

  return (
    <div>
      <div className="tree-row tree-folder" style={{ paddingInlineStart: depth * 14 + 6 }}>
        <input
          type="checkbox"
          checked={allSelected}
          ref={(el) => el && (el.indeterminate = someSelected)}
          onChange={(e) => togglePaths(paths, e.target.checked)}
        />
        <span className="tree-arrow" onClick={() => toggleExpand(node.path)}>
          {isOpen ? "▾" : "◂"}
        </span>
        <span className="tree-icon" onClick={() => toggleExpand(node.path)}>📁</span>
        <span className="tree-name" onClick={() => toggleExpand(node.path)}>{node.name}</span>
      </div>
      {isOpen &&
        (node.children || []).map((c, i) =>
          c.kind === "folder" ? (
            <FolderNode
              key={c.path || i}
              node={c}
              depth={depth + 1}
              selected={selected}
              togglePaths={togglePaths}
              expanded={expanded}
              toggleExpand={toggleExpand}
              term={term}
            />
          ) : (
            <BookNode key={i} node={c} depth={depth + 1} selected={selected} togglePaths={togglePaths} />
          )
        )}
    </div>
  );
}

function BookNode({ node, depth, selected, togglePaths }) {
  const paths = nodePaths(node);
  const checked = paths.length > 0 && paths.every((p) => selected.has(p));
  return (
    <label className="tree-row tree-book" style={{ paddingInlineStart: depth * 14 + 6 }}>
      <input type="checkbox" checked={checked} onChange={(e) => togglePaths(paths, e.target.checked)} />
      <span className="tree-icon">📄</span>
      <span className="tree-name">{node.name}</span>
    </label>
  );
}

function filterTree(nodes, term) {
  if (!term) return nodes;
  const out = [];
  for (const n of nodes) {
    if (n.kind === "folder") {
      const kids = filterTree(n.children || [], term);
      if (kids.length > 0 || n.name.includes(term)) out.push({ ...n, children: kids });
    } else if (n.name.includes(term)) {
      out.push(n);
    }
  }
  return out;
}

export default function ScopeTree({ tree, selected, setSelected }) {
  const [term, setTerm] = useState("");
  const [expanded, setExpanded] = useState(() => new Set());

  const filtered = useMemo(() => filterTree(tree, term.trim()), [tree, term]);
  const allPaths = useMemo(() => {
    const acc = [];
    tree.forEach((n) => collectBookPaths(n, acc));
    return acc;
  }, [tree]);

  function togglePaths(paths, on) {
    setSelected((prev) => {
      const next = new Set(prev);
      paths.forEach((p) => (on ? next.add(p) : next.delete(p)));
      return next;
    });
  }

  function toggleExpand(path) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  }

  return (
    <div className="scope-tree">
      <input
        type="text"
        placeholder="חיפוש בשמות הספרים…"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
      />
      <div className="scope-actions">
        <button className="btn btn-sm" onClick={() => setSelected(new Set(allPaths))}>בחר הכל</button>
        <button className="btn btn-sm" onClick={() => setSelected(new Set())}>נקה בחירות</button>
      </div>
      <div className="scope-hint muted">
        {selected.size === 0 ? "חיפוש בכל הספרים" : `חיפוש ב-${selected.size} קבצים נבחרים`}
      </div>
      <div className="tree-body">
        {filtered.map((n, i) =>
          n.kind === "folder" ? (
            <FolderNode
              key={n.path || i}
              node={n}
              depth={0}
              selected={selected}
              togglePaths={togglePaths}
              expanded={expanded}
              toggleExpand={toggleExpand}
              term={term.trim()}
            />
          ) : (
            <BookNode key={i} node={n} depth={0} selected={selected} togglePaths={togglePaths} />
          )
        )}
      </div>
    </div>
  );
}
