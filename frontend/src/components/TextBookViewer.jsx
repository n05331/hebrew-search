import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { api, stripNiqqud, stripTeamim } from "../api.js";

// מציג טקסט ספר בגלילה רציפה: חלון קטעים [first..last] שנטען דינמית לשני
// הכיוונים, עיצוב כותרות תורת-אמת/אוצריא, הדגשות חיפוש-בספר, וקפיצה למיקום.
//
// props:
//   path              נתיב קובץ הטקסט
//   fontSize          גודל גופן בסיס
//   fontFamily        משפחת גופן
//   removeNiqqud / removeTeamim   הסרת ניקוד/טעמים בתצוגה
//   hits              [{chunk,start,end}] הופעות חיפוש-בספר (אינדקס גלובלי)
//   activeHit         אינדקס ההופעה הפעילה
//   onPosition(chunk, absOffset)  דיווח מיקום גלילה נוכחי
//   onUserScroll()    נקרא בתחילת גלילת משתמש (לסגירת עץ הכותרות)
//   onMeta(data)      מטא-דאטה של הקטע הראשון שנטען (שם, has_niqqud וכו')
//   target            {chunk, offset?, seq} - יעד קפיצה מבוקר מבחוץ
//
// ref API: gotoChunk(chunk, offset?), gotoHit(globalIdx, hitList?)

const HEADING_SCALE = { 1: 1.07 * 1.07 * 1.07, 2: 1.07 * 1.07, 3: 1.07 };

function renderChunk(chunkData, opts) {
  const { fontSize, removeNiqqud, removeTeamim, hits, activeHit, hitBase } = opts;
  const text = chunkData.text;
  const headings = chunkData.headings || [];

  const clean = (s) => {
    let t = s;
    if (removeTeamim) t = stripTeamim(t);
    if (removeNiqqud) t = stripNiqqud(t);
    return t;
  };

  // הופעות בקטע זה, ממוינות
  const chunkHits = (hits || [])
    .map((h, gi) => ({ ...h, gi }))
    .filter((h) => h.chunk === chunkData.chunk)
    .sort((a, b) => a.start - b.start);

  // מרנדר טווח טקסט רגיל עם הדגשות שבתוכו
  function renderPlain(from, to, keyPrefix) {
    const nodes = [];
    let cursor = from;
    for (const h of chunkHits) {
      if (h.end <= from || h.start >= to) continue;
      const s = Math.max(h.start, from);
      const e = Math.min(h.end, to);
      if (s > cursor) nodes.push(clean(text.slice(cursor, s)));
      nodes.push(
        <mark
          key={keyPrefix + "-h" + h.gi}
          className={"hl" + (h.gi === activeHit ? " active" : "")}
          data-hit={h.gi}
        >
          {clean(text.slice(s, e))}
        </mark>
      );
      cursor = e;
    }
    if (cursor < to) nodes.push(clean(text.slice(cursor, to)));
    return nodes;
  }

  const blocks = [];
  let pos = 0;
  headings.forEach((h, i) => {
    if (h.start > pos) {
      blocks.push(
        <span key={"t" + i}>{renderPlain(pos, h.start, "t" + i)}</span>
      );
    }
    const scale = HEADING_SCALE[h.level] || 1;
    blocks.push(
      <span
        key={"head" + i}
        className={"book-heading heading-l" + h.level}
        data-hstart={chunkData.chunk_start + h.start}
        style={{ fontSize: Math.round(fontSize * scale) + "px" }}
      >
        {renderPlain(h.start, h.end, "head" + i)}
      </span>
    );
    pos = h.end;
  });
  if (pos < text.length) {
    blocks.push(<span key="tail">{renderPlain(pos, text.length, "tail")}</span>);
  }
  return blocks;
}

const TextBookViewer = forwardRef(function TextBookViewer(
  {
    path,
    fontSize = 30,
    fontFamily = "FrankRuehl",
    removeNiqqud = false,
    removeTeamim = false,
    hits = null,
    activeHit = -1,
    onPosition,
    onUserScroll,
    onMeta,
    target = null,
  },
  ref
) {
  const [chunks, setChunks] = useState([]); // חלון רציף של קטעים
  const [totalChunks, setTotalChunks] = useState(1);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const bodyRef = useRef(null);
  const loadingRef = useRef(false);
  const prependRef = useRef(null); // {prevHeight} לשמירת מיקום בגלילה לאחור
  const pendingScrollRef = useRef(null); // {chunk, offset?, hit?} קפיצה ממתינה
  const chunksRef = useRef(chunks);
  chunksRef.current = chunks;

  const fetchChunk = useCallback(
    async (idx) => {
      const d = await api.bookText(path, idx);
      return d;
    },
    [path]
  );

  // טעינה ראשונית
  const loadWindow = useCallback(
    async (centerChunk) => {
      loadingRef.current = true;
      setLoading(true);
      setError(null);
      try {
        const first = await fetchChunk(centerChunk || 0);
        setTotalChunks(first.total_chunks);
        onMeta && onMeta(first);
        setChunks([first]);
      } catch (e) {
        setError(e.message);
        setChunks([]);
      } finally {
        setLoading(false);
        loadingRef.current = false;
      }
    },
    [fetchChunk, onMeta]
  );

  const appliedSeqRef = useRef(null);

  useEffect(() => {
    if (target) {
      appliedSeqRef.current = target.seq;
      pendingScrollRef.current = { chunk: target.chunk || 0, offset: target.offset };
      loadWindow(target.chunk || 0);
    } else {
      appliedSeqRef.current = null;
      pendingScrollRef.current = null;
      loadWindow(0);
    }
  }, [path]);

  // קפיצה מבוקרת מבחוץ (מעבר PDF->טקסט, כותרת מה-TOC, סימנייה)
  useEffect(() => {
    if (!target || appliedSeqRef.current === target.seq) return;
    appliedSeqRef.current = target.seq;
    gotoChunk(target.chunk || 0, target.offset);
  }, [target && target.seq]);

  const loadNext = useCallback(async () => {
    const cur = chunksRef.current;
    if (loadingRef.current || cur.length === 0) return;
    const last = cur[cur.length - 1];
    if (last.chunk >= last.total_chunks - 1) return;
    loadingRef.current = true;
    try {
      const d = await fetchChunk(last.chunk + 1);
      setChunks((prev) =>
        prev.length && prev[prev.length - 1].chunk === last.chunk ? [...prev, d] : prev
      );
    } catch (e) {} finally {
      loadingRef.current = false;
    }
  }, [fetchChunk]);

  const loadPrev = useCallback(async () => {
    const cur = chunksRef.current;
    if (loadingRef.current || cur.length === 0) return;
    const first = cur[0];
    if (first.chunk <= 0) return;
    loadingRef.current = true;
    try {
      const d = await fetchChunk(first.chunk - 1);
      prependRef.current = { prevHeight: bodyRef.current ? bodyRef.current.scrollHeight : 0 };
      setChunks((prev) => (prev.length && prev[0].chunk === first.chunk ? [d, ...prev] : prev));
    } catch (e) {} finally {
      loadingRef.current = false;
    }
  }, [fetchChunk]);

  // תיקון מיקום גלילה אחרי הוספת קטע בראש
  useLayoutEffect(() => {
    if (prependRef.current && bodyRef.current) {
      const diff = bodyRef.current.scrollHeight - prependRef.current.prevHeight;
      bodyRef.current.scrollTop += diff;
      prependRef.current = null;
    }
  }, [chunks]);

  // ביצוע קפיצה ממתינה אחרי שהקטע נטען
  useLayoutEffect(() => {
    const pending = pendingScrollRef.current;
    if (!pending || !bodyRef.current) return;
    const el = bodyRef.current.querySelector(`[data-chunk="${pending.chunk}"]`);
    if (!el) return;
    pendingScrollRef.current = null;

    if (pending.hit != null) {
      const mark = bodyRef.current.querySelector(`mark[data-hit="${pending.hit}"]`);
      if (mark) {
        mark.scrollIntoView({ block: "center" });
        return;
      }
    }
    if (pending.offset != null) {
      // עוגן מדויק: כותרת שמתחילה בהיסט; אחרת - יחסי לאורך הקטע
      const chunkData = chunksRef.current.find((c) => c.chunk === pending.chunk);
      const abs = (chunkData ? chunkData.chunk_start : 0) + pending.offset;
      const headEl = bodyRef.current.querySelector(`[data-hstart="${abs}"]`);
      if (headEl) {
        headEl.scrollIntoView({ block: "start" });
        bodyRef.current.scrollTop -= 8;
        return;
      }
      if (chunkData && chunkData.text.length > 0) {
        const frac = pending.offset / chunkData.text.length;
        bodyRef.current.scrollTop = el.offsetTop + frac * el.offsetHeight - 60;
        return;
      }
    }
    el.scrollIntoView({ block: "start" });
  }, [chunks]);

  const gotoChunk = useCallback(
    async (chunk, offset) => {
      const cur = chunksRef.current;
      const loaded = cur.find((c) => c.chunk === chunk);
      pendingScrollRef.current = { chunk, offset };
      if (loaded) {
        // כבר טעון - מפעילים את הקפיצה ידנית ע"י עדכון state קטן
        setChunks((prev) => [...prev]);
        return;
      }
      loadingRef.current = true;
      setLoading(true);
      try {
        const d = await fetchChunk(chunk);
        setTotalChunks(d.total_chunks);
        setChunks([d]);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
        loadingRef.current = false;
      }
    },
    [fetchChunk]
  );

  const gotoHit = useCallback(
    async (globalIdx, hitList) => {
      const list = hitList || hits || [];
      const h = list[globalIdx];
      if (!h) return;
      pendingScrollRef.current = { chunk: h.chunk, hit: globalIdx };
      const loaded = chunksRef.current.find((c) => c.chunk === h.chunk);
      if (loaded) {
        setChunks((prev) => [...prev]);
        return;
      }
      loadingRef.current = true;
      try {
        const d = await fetchChunk(h.chunk);
        setTotalChunks(d.total_chunks);
        setChunks([d]);
      } catch (e) {} finally {
        loadingRef.current = false;
      }
    },
    [fetchChunk, hits]
  );

  useImperativeHandle(ref, () => ({ gotoChunk, gotoHit }), [gotoChunk, gotoHit]);

  // גלילה: טעינת המשך/התחלה + דיווח מיקום
  const lastReportRef = useRef(0);
  function onScroll() {
    const el = bodyRef.current;
    if (!el) return;
    onUserScroll && onUserScroll();
    if (el.scrollTop < 500) loadPrev();
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 800) loadNext();

    const now = Date.now();
    if (now - lastReportRef.current < 300) return;
    lastReportRef.current = now;

    // הקטע העליון הנראה + היסט משוער בתוכו
    const nodes = el.querySelectorAll("[data-chunk]");
    for (const node of nodes) {
      const bottom = node.offsetTop + node.offsetHeight;
      if (bottom > el.scrollTop) {
        const chunk = parseInt(node.getAttribute("data-chunk"), 10);
        const cd = chunksRef.current.find((c) => c.chunk === chunk);
        if (cd && onPosition) {
          const frac = Math.min(
            1,
            Math.max(0, (el.scrollTop - node.offsetTop) / Math.max(1, node.offsetHeight))
          );
          const offset = Math.round(frac * cd.text.length);
          onPosition(chunk, cd.chunk_start + offset);
        }
        break;
      }
    }
  }

  return (
    <div className="text-book-body" ref={bodyRef} onScroll={onScroll}>
      {error && <div className="error-box">{error}</div>}
      {loading && chunks.length === 0 && <div className="loading">טוען…</div>}
      {chunks.length > 0 && chunks[0].chunk > 0 && (
        <div className="chunk-edge muted">… טוען אחורה בגלילה למעלה …</div>
      )}
      {chunks.map((cd) => (
        <pre
          key={cd.chunk}
          className="doc-text"
          data-chunk={cd.chunk}
          style={{ fontSize: fontSize + "px", fontFamily: fontFamily || "inherit" }}
        >
          {renderChunk(cd, { fontSize, removeNiqqud, removeTeamim, hits, activeHit })}
        </pre>
      ))}
      {chunks.length > 0 && chunks[chunks.length - 1].chunk < totalChunks - 1 && (
        <div className="chunk-edge muted">טוען המשך…</div>
      )}
    </div>
  );
});

export default TextBookViewer;
