// Interactive tutorial: a spotlight tour across the four steps, with the decision behind each one.
import { useCallback, useEffect, useRef, useState } from "react";
import { get, post } from "../api";
import { gsap, reduced, useGSAP } from "../lib/gsap";

type Step = {
  id: string; page?: "connect" | "documents" | "data" | "ask"; target?: string; title: string; body: string; decision?: string;
  action?: { label: string; event: string; detail?: any }; afterEvent?: string; wait?: number;
};

export const STEPS: Step[] = [
  { id: "welcome", title: "Welcome to Drive DocIntel", body: "Point it at a folder of messy fund documents and get one table you can filter and question, with every number traced back to the line it came from. This two-minute tour walks the four steps and the decisions behind them." },
  { id: "google", page: "connect", target: "[data-tour=connect-google]", title: "1 · Connect Google Drive", body: "Sign in with Google and choose one folder. From then on the app watches it: new or changed files are read within a minute, deleted files are retired.", decision: "The folder is polled once a minute rather than using push notifications. Polling also catches deletions, needs no public webhook, and costs a few quota units." },
  { id: "folder", page: "connect", target: "[data-tour=connect-folder]", title: "…or a folder on this computer", body: "The same watcher works on a local folder, so you can test without any Google setup. Drop files in; press Sync now to read them straight away.", decision: "One pipeline for Drive, local folders and uploads, so the behaviour is identical wherever a file comes from." },
  { id: "reading", page: "connect", target: "[data-tour=connect-reading]", title: "Costs and re-reads", body: "Today's model spend, an optional daily cap, and one button to re-read everything when the reader improves.", decision: "Every model call is logged with its cost. Readings are versioned, so a re-read shows exactly what changed." },
  { id: "drop", page: "documents", target: "[data-tour=docs-dropzone]", title: "2 · Add documents by hand", body: "Drag PDFs, spreadsheets, Word files, emails or images here. Factsheets, statements, decks, rate sheets, invoices, brochures: all go through the same reader.", decision: "One strict schema for every kind of file. PDFs go to the model as PDFs, so there is no parser per layout and scans work. Personal ID documents are caught locally and never sent." },
  { id: "list", page: "documents", target: "[data-tour=docs-table]", title: "Every document, in plain words", body: "What kind of file, who it is from, the as-of date, how many figures and facts were read, and a status that says what to do next.", decision: "A document with no figures is not an error: a brochure still gets a summary and its key facts.", action: { label: "Open the first document", event: "docintel:open-first-doc" }, afterEvent: "docintel:open-first-doc" },
  { id: "drawer", page: "documents", target: ".drawer", title: "Inside a document", body: "A plain summary, the original in its own form (PDF viewer, spreadsheet grid, Word page, email), every figure beside the line it came from with a ✓ when that line was found in the text, the key facts, and the reading history.", decision: "The model must quote the fragment each number came from; the app checks it against the text itself. Numbers it cannot ground are flagged, never hidden.", afterEvent: "docintel:close-drawer" },
  { id: "stats", page: "data", target: "[data-tour=data-stats]", title: "3 · One table for everything", body: "Every figure from every document, normalised to fund · what · period, with the fund names de-duplicated across managers.", decision: "A long fact table with explicit period columns, so ‘best January return’ is a plain filter and Jan 2025 never mixes with Jan 2026." },
  { id: "filters", page: "data", target: "[data-tour=data-filters]", title: "Filter and export", body: "By fund, manager, what it measures, period type, year and month. Export to Excel with one click." },
  { id: "facts", page: "data", target: "[data-tour=data-facts]", title: "Key facts", body: "Everything with a value that is not a performance figure: minimums, target sizes, rates, closing dates, terms. Searchable, and each one links to its source." },
  { id: "ask", page: "ask", target: "[data-tour=ask-composer]", title: "4 · Ask the library", body: "Plain-English questions, with memory for follow-ups. The model can only see the data through three tools: search the library, read a document, query the figures.", decision: "Answers must cite. Every citation is checked against what the tools actually returned; anything else is marked unverified.", action: { label: "Ask: which fund had the best January return?", event: "docintel:ask", detail: "Which fund had the best January return?" }, afterEvent: "docintel:ask" },
  { id: "answer", page: "ask", target: "[data-tour=ask-thread]", title: "Watch it work", body: "The status shows which tool is running. Chips in the answer open the exact page; Sources list the documents used; ‘Show the work’ reveals every query and page read.", wait: 1500 },
  { id: "end", title: "That’s the whole system", body: "Drive or local folder → one reader for any file → verified figures and facts → a library you can question. Measured on a synthetic corpus at 100% precision, and on real documents with a gold set you can grow. The README has the rest, including the deploy and the PII gate." },
];

const DONE_KEY = "docintel.tour.done";
export const tourDone = () => localStorage.getItem(DONE_KEY) === "1";

/** Keep the spotlight inside the viewport for very tall targets (long tables). */
function clip(r: DOMRect): DOMRect {
  const top = Math.max(r.top, 72);
  const bottom = Math.min(r.bottom, window.innerHeight - 16);
  return new DOMRect(r.left, top, r.width, Math.max(80, bottom - top));
}

function waitFor(selector: string, timeout = 2500): Promise<HTMLElement | null> {
  return new Promise((resolve) => {
    const start = performance.now();
    const tick = () => {
      const el = document.querySelector(selector) as HTMLElement | null;
      if (el) return resolve(el);
      if (performance.now() - start > timeout) return resolve(null);
      requestAnimationFrame(tick);
    };
    tick();
  });
}

export default function Tour({ open, onClose, startAt = 0 }: { open: boolean; onClose: () => void; startAt?: number }) {
  const [i, setI] = useState(startAt);
  const [rect, setRect] = useState<DOMRect | null>(null);
  // Which step the spotlight has been placed for. The card stays hidden
  // from a step change until its target is scrolled to and measured, and
  // fades in once — keyed on this, never on the rectangle, which also
  // changes on every scroll tick while the page glides to the target.
  const [placedFor, setPlacedFor] = useState(-1);
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const spot = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const step = STEPS[Math.min(i, STEPS.length - 1)];

  useEffect(() => {
    if (!open) return;
    // A reopened tour starts unplaced: no stale spotlight, no card before its target is found.
    setI(startAt); setRect(null); setPlacedFor(-1);
    get("/api/tutorial/status").then(setStatus).catch(() => {});
  }, [open, startAt]);

  const place = useCallback(async () => {
    if (!open) return;
    if (step.page && location.hash.replace("#", "") !== step.page) { location.hash = step.page; await new Promise((r) => setTimeout(r, 350)); }
    if (!step.target) { setRect(null); setPlacedFor(i); return; }
    const el = await waitFor(step.target);
    if (!el) { setRect(null); setPlacedFor(i); return; }
    const tall = el.getBoundingClientRect().height > window.innerHeight * 0.7;
    el.scrollIntoView({ block: tall ? "start" : "center", behavior: reduced() ? "auto" : "smooth" });
    await new Promise((r) => setTimeout(r, reduced() ? 50 : 450));
    setRect(clip(el.getBoundingClientRect()));
    setPlacedFor(i);
  }, [open, step, i]);

  useEffect(() => { place(); }, [place]);
  useEffect(() => {
    if (!open) return;
    // Follow the target through resizes and scrolls, but only when it moved:
    // a fresh DOMRect per event would re-render and re-tween for nothing.
    const re = () => {
      if (!step.target) return;
      const el = document.querySelector(step.target) as HTMLElement | null;
      if (!el) return;
      const r = clip(el.getBoundingClientRect());
      setRect((prev) => (prev && Math.abs(prev.top - r.top) < 0.5 && Math.abs(prev.left - r.left) < 0.5 && Math.abs(prev.width - r.width) < 0.5 && Math.abs(prev.height - r.height) < 0.5 ? prev : r));
    };
    window.addEventListener("resize", re); window.addEventListener("scroll", re, true);
    return () => { window.removeEventListener("resize", re); window.removeEventListener("scroll", re, true); };
  }, [open, step]);

  // The spotlight glides to each new rectangle. Its inline style is written
  // only when it mounts (see below), so React never snaps it ahead of the tween.
  useGSAP(() => {
    if (!open || !rect || !spot.current) return;
    const box = { top: rect.top - 8, left: rect.left - 8, width: rect.width + 16, height: rect.height + 16 };
    if (reduced()) gsap.set(spot.current, box);
    else gsap.to(spot.current, { ...box, duration: 0.5, ease: "power3.out", overwrite: "auto" });
  }, { dependencies: [rect, open] });

  // The card fades in once per step, when that step has been placed.
  useGSAP(() => {
    if (!open || reduced() || placedFor !== i || !card.current) return;
    gsap.fromTo(card.current, { y: 10, opacity: 0 }, { y: 0, opacity: 1, duration: 0.4, ease: "power3.out", clearProps: "transform,opacity", overwrite: "auto" });
  }, { dependencies: [placedFor, open] });

  const finish = () => { localStorage.setItem(DONE_KEY, "1"); onClose(); };
  const next = async () => {
    if (step.afterEvent === "docintel:close-drawer") window.dispatchEvent(new CustomEvent("docintel:close-drawer"));
    if (i >= STEPS.length - 1) return finish();
    setI(i + 1);
  };
  const back = () => setI(Math.max(0, i - 1));
  const act = async () => {
    const a = step.action;
    if (!a) return;
    window.dispatchEvent(new CustomEvent(a.event, { detail: a.detail }));
    await new Promise((r) => setTimeout(r, a.event === "docintel:ask" ? 600 : 500));
    setI(i + 1);
  };
  const loadSample = async () => {
    setLoading(true);
    try { const r = await post("/api/tutorial/sample"); setStatus({ ...(status || {}), queued: r.queued }); } catch (e) { setStatus({ ...(status || {}), error: String(e) }); } finally { setLoading(false); }
  };

  // The rectangle the spotlight mounted with: inline style for the first
  // paint, then GSAP owns the box. Reset when the spotlight leaves.
  const mountRect = useRef<DOMRect | null>(null);
  if (!rect) mountRect.current = null;
  else if (!mountRect.current) mountRect.current = rect;

  if (!open) return null;
  const centered = !rect;
  const pending = placedFor !== i;
  const W = 420, H = 300, G = 22, vw = window.innerWidth, vh = window.innerHeight;
  let cardStyle: React.CSSProperties = { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  if (rect) {
    const clampTop = (t: number) => Math.max(16, Math.min(t, vh - H - 16));
    if (rect.right + G + W <= vw - 16) cardStyle = { top: clampTop(rect.top), left: rect.right + G };                 // beside, to the right
    else if (rect.left - G - W >= 16) cardStyle = { top: clampTop(rect.top), left: rect.left - G - W };            // beside, to the left
    else if (rect.bottom + G + H <= vh) cardStyle = { top: rect.bottom + G, left: Math.min(Math.max(16, rect.left), vw - W - 16) };   // below
    else if (rect.top - G - H >= 16) cardStyle = { top: rect.top - G - H, left: Math.min(Math.max(16, rect.left), vw - W - 16) };     // above
    else cardStyle = { bottom: 16, right: 16 };                                                                       // corner, never covering the spotlight centre
  }
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Tutorial">
      <div className="tour-dim" onClick={finish} />
      {rect && mountRect.current && <div ref={spot} className="tour-spot" style={{ top: mountRect.current.top - 8, left: mountRect.current.left - 8, width: mountRect.current.width + 16, height: mountRect.current.height + 16 }} />}
      <div ref={card} className={`tour-card ${centered ? "center" : ""} ${pending ? "pending" : ""}`} style={cardStyle}>
        <div className="eyebrow">Tutorial · {i + 1} of {STEPS.length}</div>
        <h2>{step.title}</h2>
        <p>{step.body}</p>
        {step.decision && <div className="tour-decision"><b>Decision</b> {step.decision}</div>}
        {step.id === "welcome" && status && status.documents === 0 && (
          <div className="notice" style={{ marginTop: 10 }}>
            The library is empty. {status.llm_ready ? <>Load 13 fictional sample documents first (about $0.50 of model usage)? <button className="btn sm gold" onClick={loadSample} disabled={loading || status.queued}>{status.queued ? `Reading ${status.queued} files…` : loading ? "Loading…" : "Load the sample library"}</button></> : "Set OPENROUTER_API_KEY in .env to read documents."}
            {status.error && <div className="small" style={{ color: "#7a2e2e" }}>{status.error}</div>}
          </div>
        )}
        <div className="row" style={{ marginTop: 14 }}>
          {i > 0 && <button className="btn ghost sm" onClick={back}>Back</button>}
          <span style={{ flex: 1 }} />
          <button className="linkish" onClick={finish}>Skip</button>
          {step.action ? <button className="btn gold sm" onClick={act}>{step.action.label}</button> : <button className="btn sm" onClick={next}>{i >= STEPS.length - 1 ? "Finish" : i === 0 ? "Start the tour" : "Next"}</button>}
          {step.action && <button className="btn sm ghost" onClick={next}>Next</button>}
        </div>
      </div>
    </div>
  );
}
