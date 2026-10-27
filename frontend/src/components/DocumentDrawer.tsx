import { useEffect, useState } from "react";
import { fmtValue, get, post, Me, Obs } from "../api";
import { docTypeLabel, flagText, metricLabel, Mode, periodLabel, statusLabel, baseName } from "../lib/labels";
import Chip from "./Chip";
import Drawer from "./Drawer";
import FileBadge from "./FileBadge";
import FullPreview from "./FullPreview";
import Preview, { PreviewData } from "./Preview";

type Tab = "original" | "figures" | "facts" | "history" | "text" | "json";

export default function DocumentDrawer({ docId, onClose, mode, page }: { docId: number | null; onClose: () => void; mode: Mode; page?: number }) {
  const [doc, setDoc] = useState<any>(null);
  const [prev, setPrev] = useState<PreviewData | null>(null);
  const [versions, setVersions] = useState<any[] | null>(null);
  const [lookFor, setLookFor] = useState<{ text: string; page: number } | null>(null);
  const showInOriginal = (text: string, pg: number) => { setLookFor({ text, page: pg }); setTab("original"); };
  const [tab, setTab] = useState<Tab>("original");
  const [full, setFull] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => { get<Me>("/api/me").then(setMe).catch(() => {}); }, []);
  useEffect(() => {
    setDoc(null); setPrev(null); setErr(""); setTab("original"); setLookFor(null); setFull(false);
    if (docId == null) return;
    get(`/api/documents/${docId}`).then(setDoc).catch((e) => setErr(String(e)));
    get(`/api/documents/${docId}/preview`).then(setPrev).catch(() => setPrev({ kind: "text", text: "", note: "Preview unavailable" }));
    setVersions(null);
    get(`/api/documents/${docId}/versions`).then((r) => setVersions(r.versions)).catch(() => setVersions([]));
  }, [docId]);
  const rerun = async (model?: string) => {
    setBusy(true);
    try { await post(`/api/documents/${docId}/rerun${model ? `?model=${encodeURIComponent(model)}` : ""}`); setErr(mode === "it" ? `Re-run queued${model ? ` with ${model}` : ""}.` : "Reading it again. This will update in a minute."); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const it = mode === "it";
  const flags = (doc?.flags || []) as { code: string; msg: string }[];
  return (
    <Drawer open={docId != null} onClose={onClose}>
      {err && <div className="notice" style={{ marginBottom: 10 }}>{err}</div>}
      {!doc ? <div className="empty">{err ? "" : "Loading…"}</div> : (<>
        <div className="row" style={{ gap: 8 }}><FileBadge file={doc.file} /><span className="eyebrow">{docTypeLabel(doc.doc_type, mode)}{it ? ` · ${doc.source}` : ""}</span></div>
        <h2 style={{ marginTop: 4 }}>{it ? doc.name : (doc.title || baseName(doc.name))}</h2>
        {!it && doc.title && <div className="small muted" style={{ marginTop: -4, marginBottom: 6 }}>{doc.name}</div>}
        <div className="row" style={{ marginBottom: 12 }}>
          <Chip v={doc.status} label={statusLabel(doc.status, mode)} />
          {doc.is_scanned && <Chip v="gold" label={it ? "image-only PDF" : "scanned"} />}
          {!doc.is_scanned && doc.ocr_pages > 0 && <Chip v="gold" label={it ? `OCR on ${doc.ocr_pages} page${doc.ocr_pages === 1 ? "" : "s"}` : "partly scanned"} />}
          {it ? <span className="small muted">{doc.n_rows} figures · {doc.page_count} page{doc.page_count === 1 ? "" : "s"} · {doc.model || "—"} · {doc.engine} · ${Number(doc.cost_usd).toFixed(4)} · {(doc.duration_ms / 1000).toFixed(1)}s</span>
              : <span className="small muted">{doc.n_rows} figure{doc.n_rows === 1 ? "" : "s"}{doc.n_facts ? ` · ${doc.n_facts} key fact${doc.n_facts === 1 ? "" : "s"}` : ""} · {doc.page_count} page{doc.page_count === 1 ? "" : "s"}</span>}
          <span style={{ flex: 1 }} />
          {doc.status !== "rejected" && <a className="btn ghost sm" href={`/api/documents/${doc.document_id}/original`} target="_blank" rel="noreferrer">Download</a>}
          {doc.status !== "rejected" && <button className="btn sm" onClick={() => rerun()} disabled={busy} title={me?.model}>{it ? "Re-run" : "Read again"}</button>}
          {it && me?.model_b && me.model_b !== me.model && <button className="btn sm gold" onClick={() => rerun(me.model_b)} disabled={busy} title={me.model_b}>Re-run with model B</button>}
        </div>
        {doc.summary && (
          <div className="summary">
            <div className="eyebrow">In short</div>
            <p>{doc.summary}</p>
            {(doc.key_points || []).length > 0 && <ul>{doc.key_points.map((k: string, i: number) => <li key={i}>{k}</li>)}</ul>}
          </div>
        )}
        <div className="kv">
          <span className="k">{it ? "Manager" : "From"}</span><span>{doc.manager || <i className="muted">not found</i>}</span>
          <span className="k">As of</span><span>{doc.as_of_date || <i className="muted">not found</i>}</span>
          {it && <><span className="k">Currency</span><span>{doc.currency || "—"}</span></>}
          <span className="k">{it ? "Funds named" : "Funds"}</span><span>{(doc.extraction?.funds || []).map((f: any) => f.name + (f.share_class ? ` (${f.share_class})` : "")).join("; ") || "—"}</span>
        </div>
        {doc.status === "rejected" ? <div className="flag err"><b>{it ? "Rejected by the PII gate:" : "Not allowed:"}</b> {it ? doc.error : "this looks like a personal ID document (driver's licence, passport or similar). It was not sent to the model and its content was not kept."}</div>
          : doc.error && <div className="flag err"><b>{it ? "Failed:" : "Couldn't read this file:"}</b> {doc.error}</div>}
        {flags.length > 0 && <div style={{ marginTop: 10 }}>{flags.map((f, i) => <div className="flag" key={i}>{it ? <><b>{f.code}</b> — {f.msg}</> : flagText(f, mode)}</div>)}</div>}
        {it && (doc.warnings || []).length > 0 && <div style={{ marginTop: 6 }}>{doc.warnings.map((w: string, i: number) => <div className="flag" key={i} style={{ borderColor: "var(--stone)", background: "var(--marble-2)" }}>model note: {w}</div>)}</div>}
        <div className="tabs">
          <button className={tab === "original" ? "active" : ""} onClick={() => setTab("original")}>Original</button>
          <button className={tab === "figures" ? "active" : ""} onClick={() => setTab("figures")}>Figures ({doc.observations.length})</button>
          <button className={tab === "facts" ? "active" : ""} onClick={() => setTab("facts")}>Key facts ({(doc.facts || []).length})</button>
          {versions && versions.length > 1 && <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>History ({versions.length})</button>}
          {it && <button className={tab === "text" ? "active" : ""} onClick={() => setTab("text")}>Extracted text</button>}
          {it && <button className={tab === "json" ? "active" : ""} onClick={() => setTab("json")}>Raw JSON</button>}
        </div>
        {tab === "original" && lookFor && <div className="lookfor"><span className="eyebrow">Look for{lookFor.page ? ` on page ${lookFor.page}` : ""}</span><span className="evidence">“{lookFor.text}”</span><button className="linkish" onClick={() => setLookFor(null)}>clear</button></div>}
        {tab === "original" && (
          <div className="preview-tools">
            <button className="btn ghost sm" onClick={() => setFull(true)} disabled={!prev} aria-label="Open the original in a full window">⤢ Full window</button>
            {prev && (prev.kind === "pdf" || prev.kind === "html") && <a className="btn ghost sm" href={prev.url} target="_blank" rel="noopener noreferrer">Open in a new tab</a>}
          </div>
        )}
        {tab === "original" && <Preview data={prev} page={lookFor?.page || page} />}
        {full && <FullPreview title={it ? doc.name : (doc.title || baseName(doc.name))} data={prev} page={lookFor?.page || page} onClose={() => setFull(false)} />}
        {tab === "figures" && (doc.observations.length === 0 ? <div className="empty">No figures were found in this document.</div> : (
          <table className="dt">
            <thead><tr><th>{it ? "Fund" : "Fund"}</th><th>{it ? "Metric" : "What"}</th><th>Period</th><th className="num">Value</th>{it && <th>Basis</th>}{it && <th>Conf.</th>}<th>{it ? "Evidence" : "Where it says so"}</th></tr></thead>
            <tbody>{doc.observations.map((o: Obs) => (
              <tr key={o.id}>
                <td>{o.fund}{o.share_class ? <div className="small muted">{o.share_class}</div> : null}</td>
                <td>{metricLabel(o.metric, mode)}<div className="small muted">{o.metric_label}</div></td>
                <td>{o.period_label}<div className="small muted">{periodLabel(o.period_type, mode)}{o.period_end ? ` · to ${o.period_end}` : ""}</div></td>
                <td className="num">{fmtValue(o.value, o.unit, o.currency, o.metric)}{o.annualized ? <div className="small muted">ann.</div> : null}{!it && o.basis !== "unknown" ? <div className="small muted">{o.basis}</div> : null}</td>
                {it && <td>{o.basis}</td>}
                {it && <td><Chip v={o.confidence} /></td>}
                <td><span className="evidence">“{o.evidence_text}”</span><div className="small">{o.evidence_verified ? <span className="badge-ok">✓ {it ? `found in text (${o.evidence_note})` : "matches the document"}</span> : <span className="badge-no">✗ {it ? o.evidence_note : o.evidence_note === "scanned" ? "scanned image, read visually" : "not matched to the text"}</span>}{o.page ? ` · p.${o.page}` : ""} · <button className="linkish small" onClick={() => showInOriginal(o.evidence_text, o.page)}>show in original</button></div></td>
              </tr>))}</tbody>
          </table>))}
        {tab === "facts" && ((doc.facts || []).length === 0 ? <div className="empty">No key facts were found in this document.</div> : (
          <table className="dt">
            <thead><tr><th>About</th><th>{it ? "Attribute" : "What"}</th><th>Value</th>{it && <th>Conf.</th>}<th>{it ? "Evidence" : "Where it says so"}</th></tr></thead>
            <tbody>{doc.facts.map((f: any) => (
              <tr key={f.id}>
                <td>{f.subject || <span className="muted">the document</span>}</td>
                <td>{f.attribute}</td>
                <td><b>{f.value_text}</b>{f.as_of ? <div className="small muted">as of {f.as_of}</div> : null}</td>
                {it && <td><Chip v={f.confidence} /></td>}
                <td><span className="evidence">“{f.evidence_text}”</span><div className="small">{f.evidence_verified ? <span className="badge-ok">✓ {it ? `found (${f.evidence_note})` : "matches the document"}</span> : <span className="badge-no">✗ {it ? f.evidence_note : f.evidence_note === "image-page" || f.evidence_note === "scanned" ? "read from an image" : "not matched to the text"}</span>}{f.page ? ` · p.${f.page}` : ""} · <button className="linkish small" onClick={() => showInOriginal(f.evidence_text, f.page)}>show in original</button></div></td>
              </tr>))}</tbody>
          </table>))}
        {tab === "history" && versions && (
          <div>
            {versions.map((v: any) => (
              <div className="step" key={v.document_id} style={{ borderLeft: v.is_current ? "3px solid var(--forest-2)" : undefined }}>
                <div className="small"><b>{v.created_at.replace("T", " ")}</b> · <Chip v={v.status} label={statusLabel(v.status, mode)} /> · {v.n_rows} figures · {v.n_facts} facts{it ? ` · ${v.model.split("/").pop()} · ${v.engine} · ${v.prompt_version} · $${Number(v.cost_usd).toFixed(3)}` : ""}{v.is_current ? " · current" : ""}</div>
                {v.diff && (v.diff.n_added + v.diff.n_removed + v.diff.n_changed > 0 ? (
                  <div className="small" style={{ marginTop: 6 }}>
                    Compared with the previous reading: {v.diff.n_changed} changed, {v.diff.n_added} new, {v.diff.n_removed} gone.
                    <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                      {v.diff.changed.slice(0, 8).map((c: any, i: number) => <li key={"c" + i}>{c.key}: {c.before} → <b>{c.after}</b></li>)}
                      {v.diff.added.slice(0, 5).map((a: string, i: number) => <li key={"a" + i}>new: {a}</li>)}
                      {v.diff.removed.slice(0, 5).map((a: string, i: number) => <li key={"r" + i}>gone: {a}</li>)}
                    </ul>
                  </div>) : <div className="small muted" style={{ marginTop: 4 }}>Same figures as the previous reading.</div>)}
              </div>))}
          </div>
        )}
        {it && tab === "text" && <pre style={{ whiteSpace: "pre-wrap", maxHeight: 600 }}>{doc.raw_text || "(no text layer: image-only document)"}</pre>}
        {it && tab === "json" && <pre style={{ maxHeight: 600 }}>{JSON.stringify({ extraction: doc.extraction, validation: doc.validation, llm_calls: doc.llm_calls }, null, 2)}</pre>}
      </>)}
    </Drawer>
  );
}
