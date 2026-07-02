import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import BrowseView from "./views/BrowseView.jsx";
import SearchView from "./views/SearchView.jsx";
import BookmarksView from "./views/BookmarksView.jsx";
import SettingsView from "./views/SettingsView.jsx";
import LogsDrawer from "./components/LogsDrawer.jsx";

const TABS = [
  { id: "browse", label: "עיון", icon: "📚" },
  { id: "search", label: "חיפוש", icon: "🔎" },
  { id: "bookmarks", label: "סימניות", icon: "🔖" },
  { id: "settings", label: "הגדרות", icon: "⚙️" },
];

export default function App() {
  const [tab, setTab] = useState("browse");
  const [settings, setSettings] = useState({});
  const [stats, setStats] = useState({});
  const [roots, setRoots] = useState([]);
  const [progress, setProgress] = useState({ running: false });
  const [logsOpen, setLogsOpen] = useState(false);
  const [toast, setToast] = useState(null);

  const toastTimer = useRef(null);
  const showToast = useCallback((msg, kind = "ok") => {
    setToast({ msg, kind });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const [s, r, p] = await Promise.all([api.stats(), api.getRoots(), api.progress()]);
      setStats(s);
      setRoots(r.roots);
      setProgress(p);
    } catch (e) {}
  }, []);

  useEffect(() => {
    api.getSettings().then((r) => setSettings(r.settings)).catch(() => {});
    refreshStatus();
    const t = setInterval(refreshStatus, 2000);
    return () => clearInterval(t);
  }, [refreshStatus]);

  const running = progress.running;
  const ocr = progress.ocr;
  const pct = running && progress.total ? Math.round((progress.processed / progress.total) * 100) : 0;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-icon">🔎</span>
          <span className="brand-name">חיפוש עברי</span>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={"tab" + (tab === t.id ? " active" : "")}
              onClick={() => setTab(t.id)}
            >
              <span>{t.icon}</span> {t.label}
            </button>
          ))}
        </nav>
        <div className="topbar-status">
          {running && (
            <span className="status-chip" title={progress.current}>
              מאנדקס… {progress.processed}/{progress.total} ({pct}%)
            </span>
          )}
          {!running && ocr && (ocr.running || ocr.pending > 0) && (
            <span className="status-chip chip-ocr" title={ocr.current}>
              OCR ברקע · {ocr.pending} בתור{ocr.pages > 0 ? ` · ${ocr.page}/${ocr.pages}` : ""}
            </span>
          )}
          <button className="btn btn-sm" onClick={() => setLogsOpen((v) => !v)}>יומן</button>
        </div>
      </header>

      <main className="app-main">
        {/* החלוניות נשארות טעונות במעבר בין לשוניות - המצב נשמר */}
        <div style={{ display: tab === "browse" ? "contents" : "none" }}>
          <BrowseView settings={settings} onToast={showToast} />
        </div>
        <div style={{ display: tab === "search" ? "contents" : "none" }}>
          <SearchView settings={settings} stats={stats} progress={progress} onToast={showToast} />
        </div>
        <div style={{ display: tab === "bookmarks" ? "contents" : "none" }}>
          <BookmarksView settings={settings} onToast={showToast} active={tab === "bookmarks"} />
        </div>
        {tab === "settings" && (
          <SettingsView
            settings={settings}
            onSettingsChanged={setSettings}
            roots={roots}
            onRootsChanged={refreshStatus}
            progress={progress}
            onToast={showToast}
          />
        )}
      </main>

      <LogsDrawer open={logsOpen} onClose={() => setLogsOpen(false)} />
      {toast && <div className={"toast toast-" + toast.kind}>{toast.msg}</div>}
    </div>
  );
}
