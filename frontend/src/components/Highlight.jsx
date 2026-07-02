import React from "react";

// מרנדר טקסט עם הדגשת טווחים. spans = [[start,end], ...] יחסית למחרוזת.
export default function Highlight({ text, spans }) {
  if (!spans || spans.length === 0) return <span>{text}</span>;

  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const parts = [];
  let cursor = 0;
  sorted.forEach(([start, end], i) => {
    if (start < cursor) return; // חפיפה - מדלגים
    if (start > cursor) parts.push(<span key={"t" + i}>{text.slice(cursor, start)}</span>);
    parts.push(
      <mark key={"m" + i} className="hl">
        {text.slice(start, end)}
      </mark>
    );
    cursor = end;
  });
  if (cursor < text.length) parts.push(<span key="tail">{text.slice(cursor)}</span>);
  return <>{parts}</>;
}
