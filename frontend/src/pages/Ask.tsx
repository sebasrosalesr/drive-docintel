import { useCallback, useEffect, useRef, useState } from "react";
import { streamPost } from "../api";
import DocumentDrawer from "../components/DocumentDrawer";
import Markdown, { CiteLabels } from "../components/Markdown";
import { gsap, reduced, useGSAP } from "../lib/gsap";
import { Check, MarkSwap, Phase, PhaseGlyph, Spinner } from "../components/Loaders";
import { docTypeLabel, Mode } from "../lib/labels";

type Step = { tool: string; purpose: string; sql: string; row_count: number; error: string; columns: string[]; rows: any[][]; input: any; summary: string };
type Source = { document_id: number; title: string; doc_type: string; manager: string; as_of: string | null; pages: number[]; cited: boolean };
type Msg = { id: number; role: "user" | "assistant"; text: string; status: string; phase: Phase; steps: Step[]; result: any | null; error: string; streaming: boolean };
type OpenDoc = { id: number; page?: number } | null;

const STORE = "docintel.thread.v1";
let nextId = Date.now();

export default function Ask({ openDoc, setOpenDoc, llmReady, mode }: { openDoc: OpenDoc; setOpenDoc: (d: OpenDoc) => void; llmReady: boolean; mode: Mode }) {
  const [thread, setThread] = useState<Msg[]>(() => { try { return (JSON.parse(localStorage.getItem(STORE) || "[]") as Msg[]).map((m) => ({ ...m, streaming: false, status: "", phase: "write" as Phase })); } catch { return []; } });
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { try { localStorage.setItem(STORE, JSON.stringify(thread.filter((m) => !m.streaming).slice(-40))); } catch { /* ignore */ } }, [thread]);

  useGSAP(() => {
    if (reduced()) return;
    gsap.from(".hero > *", { y: 14, opacity: 0, stagger: 0.08, clearProps: "transform,opacity" });
    gsap.from(".composer", { y: 20, opacity: 0, delay: 0.2, clearProps: "transform,opacity" });
  }, { scope: pageRef });

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "end" }); }, [thread.length, thread[thread.length - 1]?.text.length]);

  const patch = useCallback((id: number, fn: (m: Msg) => Msg) => setThread((t) => t.map((m) => (m.id === id ? fn(m) : m))), []);

  const send = useCallback(async (question: string) => {
    const text = question.trim();
    if (!text || busy || !llmReady) return;
    setQ("");
    setBusy(true);
    const history = thread.filter((m) => m.text && !m.error).slice(-8).map((m) => ({ role: m.role, content: m.text }));
    const uid = nextId++, aid = nextId++;
    setThread((t) => [...t, { id: uid, role: "user", text, status: "", phase: "connecting", steps: [], result: null, error: "", streaming: false },
                        { id: aid, role: "assistant", text: "", status: "Connecting", phase: "connecting", steps: [], result: null, error: "", streaming: true }]);
    try {
      await streamPost("/api/ask/stream", { question: text, history }, (ev) => {
        if (ev.type === "round") patch(aid, (m) => ({ ...m, text: "" }));
        else if (ev.type === "status") patch(aid, (m) => ({ ...m, status: ev.text, phase: phaseOf(ev.text, m.phase) }));
        else if (ev.type === "token") patch(aid, (m) => ({ ...m, text: m.text + ev.text, status: "", phase: "write" }));
        else if (ev.type === "step") patch(aid, (m) => ({ ...m, steps: [...m.steps, ev.step], status: ev.step.error ? "That didn't work, trying another way" : stepStatus(ev.step), phase: "connecting" }));
        else if (ev.type === "result") patch(aid, (m) => ({ ...m, text: ev.result.answer, result: ev.result, steps: ev.result.steps, status: "", streaming: false }));
        else if (ev.type === "error") patch(aid, (m) => ({ ...m, error: ev.detail, status: "", streaming: false }));
      });
    } catch (e) {
      patch(aid, (m) => ({ ...m, error: String(e), status: "", streaming: false }));
    } finally {
      setBusy(false);
      patch(aid, (m) => (m.streaming ? { ...m, streaming: false, status: "" } : m));
      taRef.current?.focus();
    }
  }, [busy, llmReady, patch, thread]);

  const onCite = useCallback((kind: string, id: number, page: number | undefined, res: any) => {
    if (kind === "doc") { setOpenDoc({ id, page }); return; }
    const col = kind === "fact" ? "fact_id" : "observation_id";
    for (const s of res?.steps || []) {
      const oi = (s.columns || []).indexOf(col), di = (s.columns || []).indexOf("document_id"), pi = (s.columns || []).indexOf("page");
      if (oi < 0 || di < 0) continue;
      const row = s.rows.find((r: any[]) => r[oi] === id);
      if (row) { setOpenDoc({ id: row[di], page: pi >= 0 && typeof row[pi] === "number" ? row[pi] : undefined }); return; }
    }
  }, [setOpenDoc]);

  const reset = () => { setThread([]); localStorage.removeItem(STORE); };
  useEffect(() => {
    const onAsk = (e: Event) => { const q = (e as CustomEvent).detail; if (typeof q === "string") send(q); };
    window.addEventListener("docintel:ask", onAsk);
    return () => window.removeEventListener("docintel:ask", onAsk);
  }, [send]);

  return (
    <div className="page ask" ref={pageRef}>
      <div className="hero">
        <div className="eyebrow">Step 4</div>
        <div className="row" style={{ alignItems: "baseline" }}><h1 style={{ flex: 1 }}>Ask the library</h1>{thread.length > 0 && <button className="btn ghost sm" onClick={reset}>New conversation</button>}</div>
        <p className="lede">{mode === "it" ? "Three tools: search the library, read a document's pages, query the figures. Every call, every row and every page the model read is shown under the answer, and each citation is checked against what it actually saw."
          : "Ask in plain English about anything in the documents. Answers quote the documents and link to the exact page; follow-up questions work."}</p>
      </div>

      <div className="thread" data-tour="ask-thread">
        {thread.map((m) => (m.role === "user" ? <UserBubble key={m.id} m={m} /> : <AssistantCard key={m.id} m={m} onCite={(k, id, pg) => onCite(k, id, pg, m.result)} openDoc={setOpenDoc} mode={mode} />))}
        <div ref={endRef} />
      </div>

      <form className="composer" data-tour="ask-composer" onSubmit={(e) => { e.preventDefault(); send(q); }}>
        <textarea ref={taRef} value={q} onChange={(e) => setQ(e.target.value)} rows={1}
          placeholder={llmReady ? "Ask about any document, fund, term or figure…" : "OPENROUTER_API_KEY is not set"}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }} disabled={!llmReady} />
        <button type="submit" className="btn gold send" disabled={!q.trim() || busy || !llmReady} aria-label="Send">{busy ? <MarkSwap size={22} /> : "↑"}</button>
        <div className="hint">Enter to send · Shift+Enter for a new line · click a <span className="cite doc">source</span> to open the page it came from</div>
      </form>
      <DocumentDrawer docId={openDoc?.id ?? null} page={openDoc?.page} onClose={() => setOpenDoc(null)} mode={mode} />
    </div>
  );
}

function phaseOf(status: string, prev: Phase): Phase {
  if (/^Searching/i.test(status)) return "search";
  if (/^Reading “/i.test(status)) return "read";
  if (/^Querying/i.test(status)) return "sql";
  if (/^Writing/i.test(status)) return "write";
  if (/^Reading the question/i.test(status) || /^Connecting/i.test(status)) return "connecting";
  return prev;
}

function stepLabel(s: Step) {
  if (s.tool === "search_documents") return `Searched · ${s.row_count} passage${s.row_count === 1 ? "" : "s"}`;
  if (s.tool === "read_document") return `Read ${s.row_count} page${s.row_count === 1 ? "" : "s"}`;
  return `Figures · ${s.row_count} row${s.row_count === 1 ? "" : "s"}`;
}

function Trail({ m }: { m: Msg }) {
  if (!m.steps.length && !m.streaming) return null;
  return (
    <div className="trail">
      {m.steps.map((s, i) => <span key={i} className={`pill ${s.error ? "err" : "done"}`}>{s.error ? "✕" : <Check />}{s.error ? "Retried" : stepLabel(s)}</span>)}
      {m.streaming && <span className="pill live"><Spinner />{m.status || (m.phase === "write" ? "Writing" : "Working")}</span>}
    </div>
  );
}

function stepStatus(s: Step) {
  if (s.tool === "search_documents") return `Found ${s.row_count} passage${s.row_count === 1 ? "" : "s"}`;
  if (s.tool === "read_document") return "Read the pages";
  return `Looked at ${s.row_count} row${s.row_count === 1 ? "" : "s"}`;
}

function UserBubble({ m }: { m: Msg }) {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => { if (!reduced()) gsap.from(ref.current, { y: 12, opacity: 0, scale: 0.98, duration: 0.45, clearProps: "transform,opacity" }); }, { scope: ref });
  return <div className="msg user" ref={ref}>{m.text}</div>;
}

function AssistantCard({ m, onCite, openDoc, mode }: { m: Msg; onCite: (kind: string, id: number, page?: number) => void; openDoc: (d: OpenDoc) => void; mode: Mode }) {
  const it = mode === "it";
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  useGSAP(() => { if (!reduced()) gsap.from(ref.current, { y: 14, opacity: 0, duration: 0.5, clearProps: "transform,opacity" }); }, { scope: ref });
  useGSAP(() => { if (open && !reduced()) gsap.from(".step", { y: 10, opacity: 0, stagger: 0.07, duration: 0.4, clearProps: "transform,opacity" }); }, { scope: ref, dependencies: [open] });
  const r = m.result;
  const labels: CiteLabels = {};
  for (const s of (r?.sources || []) as Source[]) labels[s.document_id] = s.title;
  const sources: Source[] = (r?.sources || []).filter((s: Source) => s.cited).length ? (r.sources as Source[]).filter((s) => s.cited) : (r?.sources || []);
  return (
    <div className={`msg assistant ${m.streaming ? "live" : ""}`} ref={ref}>
      {m.streaming && !m.text && <div className="status"><PhaseGlyph phase={m.phase} /> <span>{m.status || "Thinking"}</span></div>}
      <Trail m={m} />
      {m.error && <div className="notice err">{m.error}</div>}
      {m.text && <Markdown text={m.text} onCite={onCite} labels={labels} caret={m.streaming} />}
      {r && sources.length > 0 && (
        <div className="sources">
          <div className="eyebrow">Sources</div>
          <div className="source-row">{sources.map((s) => (
            <button type="button" key={s.document_id} className="source-card" onClick={() => openDoc({ id: s.document_id, page: s.pages[0] })} title={s.title}>
              <div className="t">{s.title}</div>
              <div className="small muted">{docTypeLabel(s.doc_type, mode)}{s.manager ? ` · ${s.manager}` : ""}{s.as_of ? ` · ${s.as_of}` : ""}{s.pages.length ? ` · p.${s.pages.slice(0, 6).join(", ")}` : ""}</div>
            </button>))}</div>
        </div>
      )}
      {r && (
        <div className="meta">
          <span className={`chip ${r.checked_against_data ? "done" : "failed"}`}>{r.checked_against_data ? (it ? `checked · ${r.steps.length} call${r.steps.length === 1 ? "" : "s"}` : "checked against the documents") : "not checked against the documents"}</span>
          {r.dropped_citations.length > 0 && <span className="chip failed">{r.dropped_citations.length} citation(s) unverified</span>}
          {r.uncited_numbers && <span className="chip needs_review">numbers without citations</span>}
          {it && <span className="small muted">{r.model.split("/").pop()} · ${Number(r.cost_usd).toFixed(4)} · {(r.duration_ms / 1000).toFixed(1)}s</span>}
          <span style={{ flex: 1 }} />
          {m.steps.length > 0 && <button type="button" className="linkish" onClick={() => setOpen((o) => !o)}>{open ? "Hide" : it ? "How it was answered" : "Show the work"}</button>}
        </div>
      )}
      {open && m.steps.map((s, i) => (
        <div className="step" key={i}>
          <div className="small"><b>{i + 1}. {s.tool === "search_documents" ? "Searched the library" : s.tool === "read_document" ? "Read a document" : "Queried the figures"}</b>
            {s.tool === "search_documents" ? ` for “${s.input?.query}” · ${s.row_count} passage${s.row_count === 1 ? "" : "s"}` : s.tool === "read_document" ? ` · ${s.summary}` : ` · ${s.purpose}`}
            {s.error ? <> · <span className="badge-no">{s.error}</span></> : s.tool === "run_sql" ? ` · ${s.row_count} row${s.row_count === 1 ? "" : "s"}` : ""}</div>
          {s.tool === "search_documents" && s.summary && <div className="small muted" style={{ marginTop: 4 }}>{s.summary}</div>}
          {s.sql && <pre>{s.sql}</pre>}
          {s.rows?.length > 0 && <details><summary>rows</summary>
            <div style={{ overflow: "auto" }}><table className="dt"><thead><tr>{s.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{s.rows.map((row, ri) => <tr key={ri}>{row.map((v, ci) => <td key={ci} className={typeof v === "number" ? "num" : ""}>{String(v ?? "")}</td>)}</tr>)}</tbody></table></div>
          </details>}
        </div>
      ))}
    </div>
  );
}
