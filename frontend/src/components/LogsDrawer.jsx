import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const LEVELS = ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"];

export default function LogsDrawer({ open, onClose }) {
  const [records, setRecords] = useState([]);
  const [level, setLevel] = useState("ALL");
  const lastId = useRef(0);
  const bodyRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    lastId.current = 0;
    setRecords([]);
    const poll = async () => {
      try {
        const { records: recs } = await api.logs(lastId.current, level);
        if (recs.length) {
          lastId.current = recs[recs.length - 1].id;
          setRecords((prev) => [...prev, ...recs].slice(-1000));
        }
      } catch (e) {}
    };
    poll();
    const t = setInterval(poll, 1500);
    return () => clearInterval(t);
  }, [open, level]);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [records]);

  if (!open) return null;

  return (
    <div className="logs-drawer">
      <div className="logs-header">
        <h3>יומן אבחון</h3>
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          {LEVELS.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <button className="btn btn-sm" onClick={onClose}>סגור</button>
      </div>
      <div className="logs-body" ref={bodyRef}>
        {records.map((r) => (
          <div key={r.id} className={"log-line lvl-" + r.level}>
            <span className="log-time">{r.time.replace("T", " ")}</span>
            <span className="log-level">{r.level}</span>
            <span className="log-logger">{r.logger.replace("hebrew_search.", "")}</span>
            <span className="log-msg">{r.message}</span>
          </div>
        ))}
        {records.length === 0 && <div className="muted">אין רשומות עדיין…</div>}
      </div>
    </div>
  );
}
